"""The events a run writes as it goes, for `lab run --remote` to follow.

One JSON object per line, each with a `type` and the time it happened (`at`).
The first line is always the version. A follower refuses an `events` version it
does not know and ignores fields it does not know, as Terraform's
machine-readable UI does, so adding a field needs no new version; removing one
or changing its meaning does.

```text
version       {"events": 1, "lab": "<commit lab was installed at>"}
run           {"run": "<run ID>", "precogly": "<commit>", "jobs": [...]}
job_started   {"job": "semgrep"}
job_finished  {"job": "semgrep", "status": "ok", "observations": {...} | null,
               "error": null}
run_finished  {"run": "<run ID>", "ok": true}
failed        {"error": "..."}   a run that ended before or between jobs
```
"""

from __future__ import annotations

import json
from datetime import datetime
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any, TextIO

VERSION = 1

Event = dict[str, Any]


def event(kind: str, at: datetime, **fields: Any) -> Event:
    return {"type": kind, "at": at.isoformat(), **fields}


def lab_commit() -> str:
    """The commit lab was installed at, from the install record pip and uv write.

    "unknown" for an install from a directory, which names no commit.
    """
    try:
        raw = distribution("lab").read_text("direct_url.json")
        commit = json.loads(raw or "{}").get("vcs_info", {}).get("commit_id")
    except (PackageNotFoundError, ValueError, AttributeError):
        return "unknown"
    return commit if isinstance(commit, str) else "unknown"


class EventLog:
    """Appends events to a file, a line each, flushed so a follower sees it now.

    Written directly rather than as a command: like stdout, it is lab's own
    output, and a dry run writes it too.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = path.open("a")

    def __call__(self, item: Event) -> None:
        self._file.write(json.dumps(item) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
