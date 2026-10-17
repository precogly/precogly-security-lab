"""Filesystem changes, as commands."""

from __future__ import annotations

from pathlib import Path

from lab.command.core import Command, CommandRunner, Effect, Result


def test_non_empty(path: Path) -> Command:
    # A dry run assumes the file exists: the job that would write it was not
    # run, so checking would only report its absence.
    return Command(
        ("test", "-s", str(path)), Effect.READ, check=False, dry_run=Result(0, "", "")
    )


def non_empty(runner: CommandRunner, path: Path) -> bool:
    return runner.run(test_non_empty(path)).returncode == 0


def mkdir(path: Path) -> Command:
    return Command(("mkdir", "-p", str(path)), Effect.WRITE)


def write_text(path: Path, text: str) -> Command:
    """Write `text` to `path`, replacing it. The parent must exist."""
    return Command(("tee", str(path)), Effect.WRITE, stdin=text)
