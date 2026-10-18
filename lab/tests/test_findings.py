"""Exporting findings: which ones are asked for, and what an agent receives."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl

import pytest

from lab.command.fake import FakeRunner
from lab.findings import (
    ALL,
    FindingsError,
    FindingStatus,
    StatusChoice,
    export,
    statuses,
)

URL = "https://secobserve.tail1234.ts.net"
NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
SHA = "94dd831e710fe11d7f344d0cddee3003c8819f2f"


def page(results: list[dict[str, Any]], count: int, more: bool = False) -> str:
    return json.dumps(
        {"count": count, "next": f"{URL}/next" if more else None, "results": results}
    )


PRODUCTS = [{"id": 9, "name": "Precogly Fork"}, {"id": 1, "name": "Precogly"}]
SERVICES = [{"id": 7, "name": "semgrep"}]


def record(
    products: list[dict[str, Any]] = PRODUCTS,
    services: list[dict[str, Any]] = SERVICES,
    observations: list[str] | None = None,
) -> FakeRunner:
    """A SecObserve whose name filters match substrings, as the real one does.

    Answers are passed in rather than scripted again afterwards: the fake
    queues a second answer for a path instead of replacing the first.
    """
    so = FakeRunner()
    so.respond("GET", "/api/products/", body=page(products, len(products)))
    so.respond(
        "GET",
        "/api/branches/",
        body=page([{"id": 4, "name": "maintenance"}, {"id": 2, "name": "main"}], 2),
    )
    so.respond("GET", "/api/services/", body=page(services, len(services)))
    for body in observations or [page([], 0)]:
        so.respond("GET", "/api/observations/", body=body)
    return so


def observation(id: int, **fields: Any) -> dict[str, Any]:
    return {
        "id": id,
        "title": "CVE-2024-0001 in openssl",
        "current_status": "Open",
        "current_severity": "High",
        "created": "2026-10-17T16:30:00Z",
        **fields,
    }


def query(so: FakeRunner, path: str) -> list[list[tuple[str, str]]]:
    return [list(r.query) for r in so.requests if r.url.endswith(path)]


def test_status_presets_and_slugs() -> None:
    assert statuses([]) == (
        FindingStatus.OPEN,
        FindingStatus.AFFECTED,
        FindingStatus.IN_REVIEW,
    )
    assert FindingStatus.RESOLVED not in statuses([StatusChoice.ALL])
    assert statuses([StatusChoice.ALL]) == ALL
    assert statuses([StatusChoice.FALSE_POSITIVE, StatusChoice.OPEN]) == (
        FindingStatus.OPEN,
        FindingStatus.FALSE_POSITIVE,
    )


def test_every_slug_names_a_status() -> None:
    # A slug whose member name has no status would fail only when chosen.
    presets = {StatusChoice.ACTIVE, StatusChoice.ALL}
    for choice in set(StatusChoice) - presets:
        assert statuses([choice]) == (FindingStatus[choice.name],)


def test_ids_are_taken_by_exact_name_and_every_page_is_read() -> None:
    so = record(
        observations=[
            page([observation(1)], 2, more=True),
            page([observation(2)], 2),
        ]
    )

    doc = export(so, URL, "t", statuses([]), ["semgrep"], NOW, note=print)

    [first, second] = query(so, "/api/observations/")
    assert ("product", "1") in first
    assert ("branch", "2") in first
    assert ("origin_service", "7") in first
    assert [v for k, v in first if k == "current_status"] == [
        "Open",
        "Affected",
        "In review",
    ]
    assert ("page", "1") in first
    assert ("page", "2") in second
    assert [f["id"] for f in doc["findings"]] == [1, 2]


def test_a_finding_carries_what_an_agent_needs() -> None:
    image_finding = observation(
        5,
        origin_service_name="trivy-backend",
        scanner_name="Trivy",
        vulnerability_id="CVE-2024-0001",
        vulnerability_id_aliases=[{"alias": "GHSA-xxxx"}],
        origin_component_name="openssl",
        origin_component_version="3.0.1",
        origin_docker_image_name_tag=f"precogly-backend:{SHA}",
    )
    code_finding = observation(6, origin_source_file="backend/app.py", cwe=89)
    so = record(observations=[page([image_finding, code_finding], 2)])
    image, code = export(so, URL, "t", statuses([]), None, NOW, note=print)["findings"]

    assert image["link"] == f"{URL}/#/observations/5/show"
    assert image["cves"] == ["CVE-2024-0001", "GHSA-xxxx"]
    assert (image["component"], image["version"]) == ("openssl", "3.0.1")
    assert image["commit"] == SHA
    # SecObserve records no commit for a code scan.
    assert (code["path"], code["cwe"], code["commit"]) == ("backend/app.py", 89, None)


def test_nothing_uploaded_is_an_empty_export_with_a_note() -> None:
    so = record(services=[])
    notes: list[str] = []

    doc = export(so, URL, "t", statuses([]), ["grype-backend"], NOW, note=notes.append)

    assert doc["findings"] == []
    assert notes == ["no run has uploaded grype-backend yet"]
    assert not query(so, "/api/observations/")


def test_a_missing_product_is_an_error() -> None:
    # A substring match only: no product is named exactly Precogly.
    so = record(products=[{"id": 9, "name": "Precogly Fork"}])
    with pytest.raises(FindingsError, match="first boot"):
        export(so, URL, "t", statuses([]), None, NOW, note=print)


def test_a_record_that_changes_mid_export_is_an_error() -> None:
    so = record(observations=[page([observation(1)], 3)])
    with pytest.raises(FindingsError, match="run it again"):
        export(so, URL, "t", statuses([]), None, NOW, note=print)


def test_the_token_is_a_header_on_every_request() -> None:
    so = record()
    export(so, URL, "so-token", statuses([]), None, NOW, note=print)
    assert so.requests
    for request in so.requests:
        assert request.headers == {"Authorization": "APIToken so-token"}
        assert "so-token" not in request.full_url()
        assert all("so-token" not in v for _, v in parse_qsl(request.full_url()))
