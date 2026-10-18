"""Preparing a job's SARIF report for upload to SecObserve."""

from __future__ import annotations

import json
from typing import Any

from lab.job import Input

# Where Precogly's checkout is mounted in a job's container (see container.py).
SOURCE_MOUNT = f"/in/{Input.SOURCE}/"


class SarifError(ValueError):
    """A report that is not SARIF."""


def prepare(report: str, job: str) -> dict[str, Any]:
    """Make a job's report fit for upload, and return it.

    Paths under the source mount become relative to Precogly's repository. A
    finding matches its earlier self by its location, so a path that depended
    on where the source was mounted would make every finding look new. Each run
    is also tagged with the job's name as its category, which keeps two jobs
    using one tool apart in any SARIF consumer.
    """
    try:
        doc: Any = json.loads(report)
    except ValueError as err:
        raise SarifError(f"not JSON: {err}") from None
    if not isinstance(doc, dict):
        raise SarifError("not a JSON object: not a SARIF report")
    runs = doc.get("runs")
    if not isinstance(runs, list) or not runs:
        raise SarifError("no runs: not a SARIF report")

    for run in runs:
        run["automationDetails"] = {"id": f"{job}/"}
        for result in run.get("results", []):
            for location in result.get("locations", []):
                artifact = location.get("physicalLocation", {}).get("artifactLocation")
                if isinstance(artifact, dict) and isinstance(artifact.get("uri"), str):
                    artifact["uri"] = repo_path(artifact["uri"])
    prepared: dict[str, Any] = doc
    return prepared


def repo_path(uri: str) -> str:
    """`/in/precogly-source/backend/x.py` (or its file:// form) to `backend/x.py`.

    Anything else, such as a path inside an image, is left alone.
    """
    path = uri.removeprefix("file://")
    return path.removeprefix(SOURCE_MOUNT) if path.startswith(SOURCE_MOUNT) else uri
