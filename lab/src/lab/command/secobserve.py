"""SecObserve's API: uploading a report, and reading the record."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from lab.command.core import (
    CommandError,
    CommandRunner,
    Effect,
    HttpRequest,
    HttpResponse,
)

PRODUCT = "Precogly"
BRANCH = "main"
_COUNT_FIELDS = ("observations_new", "observations_updated", "observations_resolved")


@dataclass(frozen=True)
class Upload:
    report: Path
    # The job's name. Product, branch, service and file name together are one
    # vulnerability check, so each job is one check, uploaded every run.
    service: str
    # "precogly-backend:94dd831" for image scans, so findings name the commit.
    docker_image: str | None = None


@dataclass(frozen=True)
class Counts:
    new: int
    updated: int
    resolved: int


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"APIToken {token}"}


def upload(url: str, token: str, request: Upload) -> HttpRequest:
    """POST /api/import/file_upload_observations_by_name/.

    SecObserve resolves whatever this report no longer contains, which is why a
    report from a failed job must never get here.
    """
    form = {
        "product_name": PRODUCT,
        "branch_name": BRANCH,
        "service": request.service,
    }
    if request.docker_image:
        form["docker_image_name_tag"] = request.docker_image
    return HttpRequest(
        "POST",
        f"{url}/api/import/file_upload_observations_by_name/",
        Effect.WRITE,
        headers=_auth(token),
        form=form,
        file=("file", request.report),
        timeout=300,
        dry_run=HttpResponse(200, json.dumps(dict.fromkeys(_COUNT_FIELDS, 0))),
    )


def submit(runner: CommandRunner, url: str, token: str, request: Upload) -> Counts:
    """Upload, and return how many observations were new, updated and resolved."""
    sent = upload(url, token, request)
    body = runner.request(sent).body
    try:
        doc = json.loads(body)
        return Counts(
            new=int(doc["observations_new"]),
            updated=int(doc["observations_updated"]),
            resolved=int(doc["observations_resolved"]),
        )
    except (ValueError, KeyError, TypeError):
        raise CommandError(sent, f"unexpected response: {body[:300]!r}") from None


def get(
    runner: CommandRunner,
    url: str,
    token: str,
    path: str,
    query: Sequence[tuple[str, str]] = (),
) -> Any:
    """GET an API path, such as `/api/observations/`, and return its JSON."""
    sent = HttpRequest(
        "GET", f"{url}{path}", Effect.READ, query=tuple(query), headers=_auth(token)
    )
    body = runner.request(sent).body
    try:
        return json.loads(body)
    except ValueError:
        raise CommandError(sent, f"not JSON: {body[:300]!r}") from None


def health(runner: CommandRunner, url: str) -> None:
    """Fail unless SecObserve answers. Needs no token."""
    runner.request(HttpRequest("GET", f"{url}/api/status/health/", Effect.READ))


def create_token(
    runner: CommandRunner,
    url: str,
    user: str,
    password: str,
    name: str,
    expires: date,
) -> str:
    """Mint a user API token from the user's password, and return it."""
    sent = HttpRequest(
        "POST",
        f"{url}/api/authentication/create_user_api_token/",
        Effect.WRITE,
        json={
            "username": user,
            "password": password,
            "name": name,
            "expiration_date": expires.isoformat(),
        },
        secret=frozenset({"password"}),
    )
    body = runner.request(sent).body
    try:
        token = json.loads(body)["token"]
    except (ValueError, KeyError, TypeError):
        # The body is not shown: it may hold the token.
        raise CommandError(sent, "unexpected response, with no token") from None
    if not isinstance(token, str) or not token:
        raise CommandError(sent, "unexpected response, with no token")
    return token


def revoke_token(
    runner: CommandRunner, url: str, user: str, password: str, name: str
) -> None:
    """Revoke the user's token named `name`; one that does not exist is no error."""
    runner.request(
        HttpRequest(
            "POST",
            f"{url}/api/authentication/revoke_user_api_token/",
            Effect.WRITE,
            json={"username": user, "password": password, "name": name},
            secret=frozenset({"password"}),
        )
    )
