"""A process lab starts, and what it returned."""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from lab.command.core.effect import Effect


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    effect: Effect
    # Added to the inherited environment. Values named in `secret` are never
    # shown: not in `display()`, errors, or dry-run output.
    env: Mapping[str, str] = field(default_factory=dict)
    secret: frozenset[str] = frozenset()
    timeout: float | None = None
    # A non-zero exit raises CommandError unless this is False. Scan jobs set it,
    # since scanners exit non-zero when they find something.
    check: bool = True
    # Stream stdout and stderr to this file instead of holding them in memory.
    output: Path | None = None
    # Fed to the command's stdin. Shown in dry-run output by size only.
    stdin: str | None = None
    # What a dry run assumes this command returned, for commands whose output
    # something downstream reads. A READ with this set is not run in a dry run:
    # it would read state an earlier, skipped WRITE never produced.
    dry_run: Result | None = None
    # Where else the program may be when `argv[0]` is not on PATH. Only the live
    # runner looks, so argv stays the same on every machine and in tests.
    search: tuple[Path, ...] = ()
    # Added to the error when the program is nowhere: how to install it.
    install_hint: str = ""

    def display(self) -> str:
        env = [
            f"{name}=<redacted>" if name in self.secret else f"{name}={value}"
            for name, value in sorted(self.env.items())
        ]
        shown = shlex.join([*env, *self.argv])
        if self.stdin is not None:
            shown += f" <<< ({len(self.stdin.encode())} bytes)"
        return shown

    def redact(self, text: str) -> str:
        for name in self.secret:
            if value := self.env.get(name):
                text = text.replace(value, "<redacted>")
        return text
