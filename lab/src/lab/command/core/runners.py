"""The runners that perform effects: live, or as a dry run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextlib import ExitStack
from typing import Protocol, TextIO

import httpx

from lab.command.core.effect import CommandError, CommandTimeout, Effect
from lab.command.core.http import HttpError, HttpRequest, HttpResponse
from lab.command.core.process import Command, Result


class CommandRunner(Protocol):
    def run(self, command: Command) -> Result: ...

    def request(self, request: HttpRequest) -> HttpResponse: ...


class LiveRunner:
    """Runs every command and sends every request."""

    def run(self, command: Command) -> Result:
        env = {**os.environ, **command.env}
        argv = command.argv
        if command.search and shutil.which(argv[0]) is None:
            found = next((p for p in command.search if p.is_file()), None)
            if found:
                argv = (str(found), *argv[1:])
        try:
            if command.output is not None:
                command.output.parent.mkdir(parents=True, exist_ok=True)
                with command.output.open("ab") as log:
                    done = subprocess.run(
                        argv,
                        env=env,
                        input=command.stdin.encode() if command.stdin else None,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=command.timeout,
                        check=False,
                    )
                result = Result(done.returncode, "", "")
            else:
                captured = subprocess.run(
                    argv,
                    env=env,
                    input=command.stdin,
                    capture_output=True,
                    text=True,
                    timeout=command.timeout,
                    check=False,
                )
                result = Result(captured.returncode, captured.stdout, captured.stderr)
        except FileNotFoundError:
            hint = f"; {command.install_hint}" if command.install_hint else ""
            problem = f"{command.argv[0]}: not installed{hint}"
            raise CommandError(command, problem) from None
        except subprocess.TimeoutExpired:
            raise CommandTimeout(
                command, f"timed out after {command.timeout}s"
            ) from None

        if command.check and result.returncode != 0:
            where = f"; see {command.output}" if command.output else ""
            problem = f"exited {result.returncode}{where}"
            raise CommandError(command, problem, result.stderr)
        return result

    def request(self, request: HttpRequest) -> HttpResponse:
        with ExitStack() as opened:
            try:
                files = None
                if request.file:
                    name, path = request.file
                    files = {name: (path.name, opened.enter_context(path.open("rb")))}
                response = httpx.request(
                    request.method,
                    request.url,
                    params=list(request.query),
                    headers=dict(request.headers),
                    data=dict(request.form) or None,
                    files=files,
                    json=dict(request.json) if request.json is not None else None,
                    timeout=request.timeout,
                )
            except OSError as err:
                raise CommandError(request, f"cannot read {err.filename}") from None
            except httpx.TimeoutException:
                raise CommandTimeout(
                    request, f"timed out after {request.timeout}s"
                ) from None
            except httpx.HTTPError as err:
                raise CommandError(request, str(err)) from None
        # Every API lab calls answers 2xx on success, so anything else fails,
        # with the body: SecObserve says there what was wrong with a request.
        if not response.is_success:
            raise HttpError(request, response.status_code, response.text)
        return HttpResponse(response.status_code, response.text)


class DryRunRunner:
    """Performs reads through `inner`; prints writes and performs nothing else."""

    def __init__(self, inner: CommandRunner, out: TextIO = sys.stdout) -> None:
        self._inner = inner
        self._out = out

    def run(self, command: Command) -> Result:
        if command.effect is Effect.READ and command.dry_run is None:
            return self._inner.run(command)
        verb = "would run" if command.effect is Effect.WRITE else "would assume"
        print(f"{verb}: {command.display()}", file=self._out)
        return command.dry_run or Result(0, "", "")

    def request(self, request: HttpRequest) -> HttpResponse:
        if request.effect is Effect.READ and request.dry_run is None:
            return self._inner.request(request)
        verb = "would send" if request.effect is Effect.WRITE else "would assume"
        print(f"{verb}: {request.display()}", file=self._out)
        return request.dry_run or HttpResponse(200, "")
