"""External effects, and the runners that perform them.

Every process lab starts is a `Command`, and every HTTP call an `HttpRequest`;
each says whether it only reads (`Effect.READ`) or changes something
(`Effect.WRITE`). `DryRunRunner` performs the reads and prints the writes, so
`--dry-run` sees the real SHA, tailnet and addresses without building, running
or uploading anything.
"""

from lab.command.core.effect import CommandError, CommandTimeout, Effect
from lab.command.core.http import HttpRequest, HttpResponse
from lab.command.core.process import Command, Result
from lab.command.core.runners import CommandRunner, DryRunRunner, LiveRunner

__all__ = [
    "Command",
    "CommandError",
    "CommandRunner",
    "CommandTimeout",
    "DryRunRunner",
    "Effect",
    "HttpRequest",
    "HttpResponse",
    "LiveRunner",
    "Result",
]
