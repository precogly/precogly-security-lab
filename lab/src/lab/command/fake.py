"""A runner for tests: records every effect, performs none."""

from __future__ import annotations

from urllib.parse import urlsplit

from lab.command.core import (
    Command,
    CommandError,
    CommandTimeout,
    HttpError,
    HttpRequest,
    HttpResponse,
    Result,
)


class FakeRunner:
    """Answers commands and requests from scripted results.

    Commands match by argv prefix, and the longest matching prefix wins, so a
    test can script `docker` broadly and `docker image inspect` specifically.
    Requests match by method and URL path; scripting one path several times
    answers successive requests in order, and the last answer repeats.
    Anything unscripted succeeds with no output.
    """

    def __init__(self) -> None:
        self.commands: list[Command] = []
        self.requests: list[HttpRequest] = []
        self._results: dict[tuple[str, ...], Result | None] = {}
        self._responses: dict[tuple[str, str], list[HttpResponse]] = {}

    def on(self, *prefix: str, stdout: str = "", returncode: int = 0) -> None:
        self._results[prefix] = Result(returncode, stdout, "")

    def times_out(self, *prefix: str) -> None:
        """Commands matching `prefix` raise CommandTimeout."""
        self._results[prefix] = None

    def respond(
        self, method: str, path: str, body: str = "", status: int = 200
    ) -> None:
        self._responses.setdefault((method, path), []).append(
            HttpResponse(status, body)
        )

    def run(self, command: Command) -> Result:
        self.commands.append(command)
        matches = [p for p in self._results if command.argv[: len(p)] == p]
        result = self._results[max(matches, key=len)] if matches else Result(0, "", "")
        if result is None:
            raise CommandTimeout(command, f"timed out after {command.timeout}s")
        if command.check and result.returncode != 0:
            raise CommandError(command, f"exited {result.returncode}", result.stderr)
        return result

    def request(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        queued = self._responses.get((request.method, urlsplit(request.url).path))
        response = HttpResponse(200, "")
        if queued:
            response = queued.pop(0) if len(queued) > 1 else queued[0]
        if not 200 <= response.status < 300:
            raise HttpError(request, response.status, response.body)
        return response

    def argvs(self) -> list[tuple[str, ...]]:
        return [command.argv for command in self.commands]
