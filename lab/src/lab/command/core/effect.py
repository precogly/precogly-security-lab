"""What every effect declares, and how one fails."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

# Lines of stderr or response body kept in an error message. Arbitrary: enough
# for a traceback's last frames, short enough to read.
_TAIL_LINES = 20


class Effect(Enum):
    READ = "read"
    WRITE = "write"


class Shown(Protocol):
    """An effect that can be printed with its secrets removed."""

    def display(self) -> str: ...

    def redact(self, text: str) -> str: ...


class CommandError(RuntimeError):
    """An effect that could not run, timed out, or failed when it had to pass."""

    def __init__(self, effect: Shown, problem: str, detail: str = "") -> None:
        tail = "\n".join(effect.redact(detail).strip().splitlines()[-_TAIL_LINES:])
        message = f"{effect.display()}\n  {problem}"
        super().__init__(f"{message}\n{tail}" if tail else message)


class CommandTimeout(CommandError):
    """An effect that ran past its timeout.

    A command is killed, but only the process lab started. For `docker run` that
    is the client, and the container keeps running until killed by name.
    """
