"""External commands, and the runners that execute them.

Every command lab runs is a `Command` that says whether it only reads
(`Effect.READ`) or changes something (`Effect.WRITE`). `DryRunRunner` runs the
reads and prints the writes, so `--dry-run` sees the real SHA, tailnet and
addresses without building, running or importing anything.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, TextIO

# Lines of stderr kept in an error message. Arbitrary: enough for a traceback's
# last frames, short enough to read.
_STDERR_TAIL = 20


class Effect(Enum):
    READ = "read"
    WRITE = "write"


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

    def display(self) -> str:
        env = [
            f"{name}=<redacted>" if name in self.secret else f"{name}={value}"
            for name, value in sorted(self.env.items())
        ]
        return shlex.join([*env, *self.argv])

    def redact(self, text: str) -> str:
        for name in self.secret:
            if value := self.env.get(name):
                text = text.replace(value, "<redacted>")
        return text


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str


class CommandError(RuntimeError):
    """A command that could not run, timed out, or failed when it had to pass."""

    def __init__(self, command: Command, problem: str, stderr: str = "") -> None:
        tail = "\n".join(command.redact(stderr).strip().splitlines()[-_STDERR_TAIL:])
        message = f"{command.display()}\n  {problem}"
        super().__init__(f"{message}\n{tail}" if tail else message)


class CommandRunner(Protocol):
    def run(self, command: Command) -> Result: ...


class SubprocessRunner:
    """Runs every command."""

    def run(self, command: Command) -> Result:
        env = {**os.environ, **command.env}
        try:
            if command.output is not None:
                command.output.parent.mkdir(parents=True, exist_ok=True)
                with command.output.open("ab") as log:
                    done = subprocess.run(
                        command.argv,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=command.timeout,
                        check=False,
                    )
                result = Result(done.returncode, "", "")
            else:
                captured = subprocess.run(
                    command.argv,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=command.timeout,
                    check=False,
                )
                result = Result(captured.returncode, captured.stdout, captured.stderr)
        except FileNotFoundError:
            raise CommandError(command, f"{command.argv[0]}: not installed") from None
        except subprocess.TimeoutExpired:
            raise CommandError(command, f"timed out after {command.timeout}s") from None

        if command.check and result.returncode != 0:
            where = f"; see {command.output}" if command.output else ""
            problem = f"exited {result.returncode}{where}"
            raise CommandError(command, problem, result.stderr)
        return result


class DryRunRunner:
    """Runs reads through `inner`; prints writes and runs nothing else."""

    def __init__(self, inner: CommandRunner, out: TextIO = sys.stdout) -> None:
        self._inner = inner
        self._out = out

    def run(self, command: Command) -> Result:
        if command.effect is Effect.READ:
            return self._inner.run(command)
        print(f"would run: {command.display()}", file=self._out)
        return Result(0, "", "")
