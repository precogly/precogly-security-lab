"""Checking Precogly out at exactly one commit."""

from __future__ import annotations

from pathlib import Path

from lab.command.core import Command, Effect

PRECOGLY_REPO = "https://github.com/precogly/precogly.git"


def checkout(sha: str, dest: Path) -> list[Command]:
    """Commands that leave `dest` holding Precogly at `sha` and nothing else.

    Fetching the one commit rather than cloning the branch: the branch may have
    moved since Terraform resolved it, and the checkout has to be the commit
    the instance runs.
    """
    git = ("git", "-C", str(dest))
    return [
        Command(("git", "init", "--quiet", str(dest)), Effect.WRITE),
        Command((*git, "remote", "add", "origin", PRECOGLY_REPO), Effect.WRITE),
        Command(
            (*git, "fetch", "--quiet", "--depth", "1", "origin", sha), Effect.WRITE
        ),
        Command((*git, "checkout", "--quiet", "--detach", "FETCH_HEAD"), Effect.WRITE),
    ]
