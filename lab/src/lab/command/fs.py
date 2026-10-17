"""Filesystem changes, as commands."""

from __future__ import annotations

from pathlib import Path

from lab.command.core import Command, Effect


def mkdir(path: Path) -> Command:
    return Command(("mkdir", "-p", str(path)), Effect.WRITE)


def write_text(path: Path, text: str) -> Command:
    """Write `text` to `path`, replacing it. The parent must exist."""
    return Command(("tee", str(path)), Effect.WRITE, stdin=text)
