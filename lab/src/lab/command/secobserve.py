"""Uploading a report to SecObserve, through curl."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lab.command.core import Command, CommandError, CommandRunner, Effect, Result

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


def upload(url: str, token: str, request: Upload) -> Command:
    """POST /api/import/file_upload_observations_by_name/.

    The token goes in on stdin as a header (`-H @-`), never on the command
    line. SecObserve resolves whatever this report no longer contains, which is
    why a report from a failed job must never get here.
    """
    fields = {
        "product_name": PRODUCT,
        "branch_name": BRANCH,
        "service": request.service,
    }
    if request.docker_image:
        fields["docker_image_name_tag"] = request.docker_image
    argv = ["curl", "--silent", "--show-error", "--fail-with-body", "-H", "@-"]
    for key, value in fields.items():
        # --form-string, not -F: a value starting with @ or < is sent as text.
        argv += ["--form-string", f"{key}={value}"]
    argv += ["-F", f"file=@{request.report}"]
    argv.append(f"{url}/api/import/file_upload_observations_by_name/")
    return Command(
        tuple(argv),
        Effect.WRITE,
        stdin=f"Authorization: APIToken {token}\n",
        timeout=300,
        dry_run=Result(0, json.dumps(dict.fromkeys(_COUNT_FIELDS, 0)), ""),
    )


def submit(runner: CommandRunner, url: str, token: str, request: Upload) -> Counts:
    """Upload, and return how many observations were new, updated and resolved."""
    command = upload(url, token, request)
    body = runner.run(command).stdout
    try:
        doc = json.loads(body)
        return Counts(
            new=int(doc["observations_new"]),
            updated=int(doc["observations_updated"]),
            resolved=int(doc["observations_resolved"]),
        )
    except (ValueError, KeyError, TypeError):
        raise CommandError(command, f"unexpected response: {body[:300]!r}") from None
