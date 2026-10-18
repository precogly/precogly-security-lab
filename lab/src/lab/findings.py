"""Exporting SecObserve's findings as JSON, for triage outside its UI.

The export is the record, deduplicated and with the team's assessments applied,
in a small versioned schema an agent can read without a credential.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

from lab.command import CommandRunner
from lab.command import secobserve as api

# Bumped when a field is removed or changes meaning; adding one does not.
SCHEMA = 1

# Arbitrary: a thousand findings in five requests, each response a few MB.
PAGE_SIZE = 200


class FindingStatus(StrEnum):
    """SecObserve's statuses, valued as its API spells them.

    From `Status` in backend/application/core/types.py, v1.61.0.
    """

    OPEN = "Open"
    AFFECTED = "Affected"
    IN_REVIEW = "In review"
    RESOLVED = "Resolved"
    DUPLICATE = "Duplicate"
    FALSE_POSITIVE = "False positive"
    NOT_AFFECTED = "Not affected"
    NOT_SECURITY = "Not security"
    RISK_ACCEPTED = "Risk accepted"


class StatusChoice(StrEnum):
    """What `--status` accepts: a preset, or one status spelt as a slug."""

    ACTIVE = "active"
    ALL = "all"
    OPEN = "open"
    AFFECTED = "affected"
    IN_REVIEW = "in-review"
    RESOLVED = "resolved"
    DUPLICATE = "duplicate"
    FALSE_POSITIVE = "false-positive"
    NOT_AFFECTED = "not-affected"
    NOT_SECURITY = "not-security"
    RISK_ACCEPTED = "risk-accepted"


# SecObserve's STATUS_ACTIVE: nobody has decided these yet.
ACTIVE = (FindingStatus.OPEN, FindingStatus.AFFECTED, FindingStatus.IN_REVIEW)
# Resolved means the scanner stopped reporting the finding: nothing to triage.
ALL = tuple(s for s in FindingStatus if s is not FindingStatus.RESOLVED)

_SHA = re.compile(r"[0-9a-f]{40}")


class FindingsError(ValueError):
    """The record does not hold what an export needs."""


def statuses(chosen: Sequence[StatusChoice]) -> tuple[FindingStatus, ...]:
    """`--status` values to statuses, in SecObserve's order; none means active."""
    picked: set[FindingStatus] = set()
    for choice in chosen or [StatusChoice.ACTIVE]:
        if choice is StatusChoice.ACTIVE:
            picked.update(ACTIVE)
        elif choice is StatusChoice.ALL:
            picked.update(ALL)
        else:
            # Every other choice shares its member name with a status.
            picked.add(FindingStatus[choice.name])
    return tuple(s for s in FindingStatus if s in picked)


def _lookup(found: Any, name: str, kind: str) -> int | None:
    """The ID of the result named exactly `name`, or None if there is none.

    The name filters on products and branches match substrings, so `main`
    would also find `maintenance`; only an exact name is taken.
    """
    exact = [r["id"] for r in found["results"] if r["name"] == name]
    if len(exact) > 1:
        raise FindingsError(f"SecObserve has {len(exact)} {kind}s named {name!r}")
    return int(exact[0]) if exact else None


def export(
    runner: CommandRunner,
    url: str,
    token: str,
    wanted: Sequence[FindingStatus],
    job: str | None,
    now: datetime,
    note: Callable[[str], None],
) -> dict[str, Any]:
    """Read the findings in `wanted` statuses, of one job or every job.

    `note` is told when there is nothing to read because nothing has been
    uploaded yet, which exports as no findings.
    """

    def get(path: str, query: Sequence[tuple[str, str]]) -> Any:
        return api.get(runner, url, token, path, query)

    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "exported": now.isoformat(),
        "source": url,
        "statuses": [s.value for s in wanted],
        "job": job,
        "findings": [],
    }
    products = get("/api/products/", [("name", api.PRODUCT)])
    product = _lookup(products, api.PRODUCT, "product")
    if product is None:
        raise FindingsError(
            f"SecObserve has no product named {api.PRODUCT!r}; the SecObserve box "
            "creates it at first boot, so check that boot's log"
        )
    branches = get("/api/branches/", [("product", str(product)), ("name", api.BRANCH)])
    branch = _lookup(branches, api.BRANCH, "branch")
    if branch is None:
        note(f"no run has uploaded to {api.PRODUCT} yet")
        return doc
    query = [("product", str(product)), ("branch", str(branch))]
    query += [("current_status", s.value) for s in wanted]
    if job:
        services = get("/api/services/", [("product", str(product)), ("name", job)])
        service = _lookup(services, job, "service")
        if service is None:
            note(f"no run has uploaded {job} yet")
            return doc
        query.append(("origin_service", str(service)))
    query += [("ordering", "id"), ("page_size", str(PAGE_SIZE))]

    observations: list[dict[str, Any]] = []
    page = 1
    while True:
        found = get("/api/observations/", [*query, ("page", str(page))])
        observations += found["results"]
        if not found.get("next"):
            break
        page += 1
    if len(observations) != found["count"]:
        raise FindingsError(
            f"read {len(observations)} findings of {found['count']}: the record "
            "changed during the export; run it again"
        )
    doc["findings"] = [_finding(url, o) for o in observations]
    return doc


def _finding(url: str, o: dict[str, Any]) -> dict[str, Any]:
    image = o.get("origin_docker_image_name_tag") or None
    # lab tags an image scan with the commit it scanned; nothing else in the
    # record says which commit a finding came from.
    tag = image.rpartition(":")[2] if image else ""
    cves = [o["vulnerability_id"]] if o.get("vulnerability_id") else []
    cves += [a["alias"] for a in o.get("vulnerability_id_aliases") or []]
    return {
        "id": o["id"],
        "link": f"{url}/#/observations/{o['id']}/show",
        "job": o.get("origin_service_name") or None,
        "scanner": o.get("scanner_name") or None,
        "status": o["current_status"],
        "severity": o["current_severity"],
        "title": o["title"],
        "cwe": o.get("cwe"),
        "cves": cves,
        "component": o.get("origin_component_name") or None,
        "version": o.get("origin_component_version") or None,
        "path": o.get("origin_source_file") or None,
        "line": o.get("origin_source_line_start"),
        "endpoint": o.get("origin_endpoint_url") or None,
        "image": image,
        "commit": tag if _SHA.fullmatch(tag) else None,
        "first_seen": o["created"],
        "description": o.get("description") or "",
    }
