"""List every URL pattern Precogly's Django URL configuration routes, as JSON.

The first half of the cross-tenant harness. It runs inside Precogly's backend
image, at the commit the instance deploys, and prints one JSON document to
stdout for the replayer to read. Nothing is stored between runs, because a
stored route list goes stale when the code moves and then silently skips every
route added since.

    docker run --rm -v "$PWD/lab/src/lab/harness:/harness:ro" \
        -e DJANGO_SETTINGS_MODULE=config.settings.production \
        precogly-backend:<sha> python /harness/route_walk.py

It walks Django's whole resolver rather than only the DRF routers, because
Precogly also routes hand-written views with plain ``path()`` (such as
``scoring-methods/`` in ``apps/threats/urls.py``), and a router walk would
miss them.

Each route comes out as a URL template, ``/api/threats/{pk}/``, with the names
of its parameters. A pattern this script cannot turn into a template is still
listed, with ``template`` set to null and the raw pattern in ``pattern``, so
the replayer can name it as skipped instead of losing it.

Imports only the standard library and Django, which the backend image already
has, so the script can be mounted in without installing anything.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any

import django

django.setup()

from django.urls import URLPattern, URLResolver, get_resolver  # noqa: E402
from django.urls.resolvers import RegexPattern, RoutePattern  # noqa: E402


@dataclass(frozen=True)
class Route:
    """One routed URL pattern, flattened from the include tree above it."""

    # The full pattern as Django matches it: the prefixes of every include
    # above it joined to its own, in each pattern's own syntax.
    pattern: str
    # The pattern as a URL with `{name}` where each parameter goes, or None if
    # some part of it could not be converted.
    template: str | None
    params: list[str]
    name: str | None
    # Dotted path of the view: the ViewSet or APIView class for DRF views,
    # the function otherwise.
    view: str
    # For a DRF ViewSet route, HTTP method to action ({"get": "retrieve"});
    # empty for anything else.
    actions: dict[str, str]
    # True for the `.{format}` copy DRF's DefaultRouter adds beside every
    # route (`/api/threats/{pk}.json`). Same view, same authorization, so the
    # replayer can skip these by name rather than replay every route twice.
    format_suffix: bool


# A named group in a regex pattern. Its body may not contain a parenthesis;
# DRF's default lookup regex, `[^/.]+`, does not, and a body that does makes
# the conversion below give up rather than guess.
NAMED_GROUP = re.compile(r"\(\?P<(?P<name>\w+)>[^()]*\)")

# A converter in a path() pattern: `<int:pk>` or `<pk>`.
PATH_CONVERTER = re.compile(r"<(?:\w+:)?(?P<name>\w+)>")


def to_template(part: RoutePattern | RegexPattern) -> tuple[str, list[str]] | None:
    """Turn one pattern segment into URL text with `{name}` placeholders.

    Returns None for a regex segment that still contains regex syntax once its
    named groups and anchors are removed: an alternation, an optional part, a
    character class outside a group. Such a segment has no single URL, so a
    template would be a guess.
    """
    # str() is the public way to get a pattern's text, for both kinds.
    raw = str(part)
    if isinstance(part, RoutePattern):
        params = [m["name"] for m in PATH_CONVERTER.finditer(raw)]
        return PATH_CONVERTER.sub(lambda m: "{" + m["name"] + "}", raw), params

    params = [m["name"] for m in NAMED_GROUP.finditer(raw)]
    text = NAMED_GROUP.sub(lambda m: "{" + m["name"] + "}", raw)
    text = text.removeprefix("^").removesuffix("$")
    # A trailing optional slash, which dj_rest_auth's patterns and DRF's
    # format-suffix variants end in. The URL with the slash matches, so the
    # template takes it. Measured at 94dd831: without this, 175 of 366 api/
    # routes had no template.
    if text.endswith("/?"):
        text = text.removesuffix("?")
    # Whatever regex syntax is left means the segment has no single URL. The
    # check runs before unescaping, while `\.` is still distinguishable from a
    # bare `.`, which matches any character.
    if re.search(r"[\^$.|?*+()\[\]]", re.sub(r"\\[./-]", "", text)) or re.search(
        r"\\[^./-]", text
    ):
        return None
    # Escaped dots, slashes and hyphens are literal URL characters.
    text = re.sub(r"\\([./-])", r"\1", text)
    return text, params


def view_path(pattern: URLPattern) -> tuple[str, dict[str, str]]:
    """Name the view behind a pattern, and its ViewSet actions if it has any.

    DRF's `as_view()` sets `cls` on the function it returns, and a ViewSet's
    also carries `actions`, the method-to-action map the router gave it.
    """
    callback: Any = pattern.callback
    cls = getattr(callback, "cls", None)
    target = cls if cls is not None else callback
    name = f"{target.__module__}.{target.__qualname__}"
    actions = dict(getattr(callback, "actions", None) or {})
    return name, actions


def walk(
    entries: list[URLPattern | URLResolver],
    prefix: list[RoutePattern | RegexPattern],
) -> list[Route]:
    """Flatten the include tree under `entries`, carrying the prefixes above."""
    routes: list[Route] = []
    for entry in entries:
        parts = [*prefix, entry.pattern]
        if isinstance(entry, URLResolver):
            routes.extend(walk(entry.url_patterns, parts))
            continue

        converted = [to_template(part) for part in parts]
        if all(c is not None for c in converted):
            template = "/" + "".join(c[0] for c in converted if c is not None)
            params = [p for c in converted if c is not None for p in c[1]]
        else:
            template = None
            params = []
        view, actions = view_path(entry)
        routes.append(
            Route(
                pattern="".join(str(part) for part in parts),
                template=template,
                params=params,
                name=entry.name,
                view=view,
                actions=actions,
                format_suffix="format" in params,
            )
        )
    return routes


def main() -> int:
    routes = walk(get_resolver().url_patterns, [])
    json.dump([asdict(route) for route in routes], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
