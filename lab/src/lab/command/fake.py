"""A runner for tests: records every command, runs none."""

from __future__ import annotations

from lab.command.core import Command, CommandError, Result


class FakeRunner:
    """Answers commands from scripted results, matched by argv prefix.

    The longest matching prefix wins, so a test can script `docker` broadly
    and `docker image inspect` specifically. Unscripted commands succeed with
    no output.
    """

    def __init__(self) -> None:
        self.commands: list[Command] = []
        self._results: dict[tuple[str, ...], Result] = {}

    def on(self, *prefix: str, stdout: str = "", returncode: int = 0) -> None:
        self._results[prefix] = Result(returncode, stdout, "")

    def run(self, command: Command) -> Result:
        self.commands.append(command)
        matches = [p for p in self._results if command.argv[: len(p)] == p]
        result = self._results[max(matches, key=len)] if matches else Result(0, "", "")
        if command.check and result.returncode != 0:
            raise CommandError(command, f"exited {result.returncode}", result.stderr)
        return result

    def argvs(self) -> list[tuple[str, ...]]:
        return [command.argv for command in self.commands]
