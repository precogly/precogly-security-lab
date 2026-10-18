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


def cat(path: Path) -> Command:
    # A dry run assumes an empty SARIF report: the job that would have written
    # the file was not run.
    return Command(
        ("cat", str(path)),
        Effect.READ,
        dry_run=Result(0, '{"runs": [{"results": []}]}', ""),
    )


def read_text(runner: CommandRunner, path: Path) -> str:
    return runner.run(cat(path)).stdout


def remove_tree(path: Path) -> Command:
    return Command(("rm", "-rf", "--", str(path)), Effect.WRITE)


def mkdir(path: Path) -> Command:
    return Command(("mkdir", "-p", str(path)), Effect.WRITE)


def write_text(path: Path, text: str) -> Command:
    """Write `text` to `path`, replacing it. The parent must exist."""
    return Command(("tee", str(path)), Effect.WRITE, stdin=text)
