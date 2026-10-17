"""Reimporting a report into DefectDojo's API, through curl."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from lab.command.core import Command, CommandError, CommandRunner, Effect, Result
from lab.job import ScanType

PRODUCT = "Precogly"
ENGAGEMENT = "lab: pentest"


@dataclass(frozen=True)
class Reimport:
    scan_type: ScanType
    report: Path
    # The job's name; one long-lived Test per job, so its history is the
    # job's time series.
    test_title: str
    commit_hash: str
    build_id: str
    version: str
    scan_date: date


def reimport(url: str, token: str, request: Reimport) -> Command:
    """POST /api/v2/reimport-scan/.

    The token goes in on stdin as a header (`-H @-`), so it is never on the
    command line. `close_old_findings` closes whatever this report no longer
    contains, which is why a report from a failed job must never get here.
    """
    fields = {
        "scan_type": request.scan_type.value,
        "product_name": PRODUCT,
        "engagement_name": ENGAGEMENT,
        "test_title": request.test_title,
        "auto_create_context": "true",
        "close_old_findings": "true",
        "commit_hash": request.commit_hash,
        "build_id": request.build_id,
        "version": request.version,
        "scan_date": request.scan_date.isoformat(),
    }
    argv = ["curl", "--silent", "--show-error", "--fail-with-body", "-H", "@-"]
    for key, value in fields.items():
        # --form-string, not -F: a value starting with @ or < is sent as text.
        argv += ["--form-string", f"{key}={value}"]
    argv += ["-F", f"file=@{request.report}", f"{url}/api/v2/reimport-scan/"]
    return Command(
        tuple(argv),
        Effect.WRITE,
        stdin=f"Authorization: Token {token}\n",
        timeout=300,
        dry_run=Result(0, '{"test": 0}', ""),
    )


def submit(runner: CommandRunner, url: str, token: str, request: Reimport) -> int:
    """Reimport, and return the id of the Test it landed in."""
    command = reimport(url, token, request)
    body = runner.run(command).stdout
    try:
        test = json.loads(body)["test"]
    except (ValueError, KeyError, TypeError):
        raise CommandError(command, f"unexpected response: {body[:300]!r}") from None
    if not isinstance(test, int):
        raise CommandError(command, f"unexpected test id: {test!r}")
    return test
