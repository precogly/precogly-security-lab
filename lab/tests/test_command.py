"""Commands, runners, and the effect each tool's commands declare."""

from __future__ import annotations

import io
import json
import sys
import threading
from collections.abc import Iterator
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lab.command import (
    Command,
    CommandError,
    DryRunRunner,
    Effect,
    HttpRequest,
    LiveRunner,
    aws,
    docker,
    git,
    secobserve,
    tailscale,
)
from lab.command.fake import FakeRunner

TOKEN = "so-token-0123456789abcdef"


def python(code: str, **kwargs: object) -> Command:
    return Command((sys.executable, "-c", code), Effect.READ, **kwargs)  # type: ignore[arg-type]


def test_runs_and_captures() -> None:
    result = LiveRunner().run(python("print('hello')"))
    assert (result.returncode, result.stdout) == (0, "hello\n")


def test_failure_names_the_command_and_its_stderr() -> None:
    code = "import sys; sys.stderr.write('boom\\n'); sys.exit(3)"
    with pytest.raises(CommandError, match=r"exited 3[\s\S]*boom"):
        LiveRunner().run(python(code))


def test_check_false_returns_the_failure() -> None:
    result = LiveRunner().run(python("raise SystemExit(2)", check=False))
    assert result.returncode == 2


def test_missing_program_and_timeout_are_actionable() -> None:
    with pytest.raises(CommandError, match="not installed"):
        LiveRunner().run(Command(("no-such-program-xyz",), Effect.READ))
    with pytest.raises(CommandError, match=r"timed out after 0\.2s"):
        LiveRunner().run(python("import time; time.sleep(5)", timeout=0.2))


def test_output_streams_to_a_file(tmp_path: Path) -> None:
    log = tmp_path / "run" / "job.log"
    code = "import sys; print('out'); sys.stderr.write('err\\n')"
    result = LiveRunner().run(python(code, output=log))
    assert result.stdout == ""
    # Both streams arrive; their order is not defined, since the child buffers
    # stdout to a file but writes stderr at once.
    assert sorted(log.read_text().split()) == ["err", "out"]


def test_secrets_reach_the_child_but_never_the_error() -> None:
    # The child echoes its secret to stderr and fails: the value must arrive,
    # and must not appear in what lab reports.
    code = "import os, sys; sys.stderr.write(os.environ['API_KEY']); sys.exit(1)"
    command = python(
        code, env={"API_KEY": "sk-live-1234"}, secret=frozenset({"API_KEY"})
    )
    with pytest.raises(CommandError) as err:
        LiveRunner().run(command)
    assert "sk-live-1234" not in str(err.value)
    assert "API_KEY=<redacted>" in str(err.value)


def test_dry_run_runs_reads_and_prints_writes() -> None:
    inner = FakeRunner()
    inner.on("tailscale", "status", stdout='{"MagicDNSSuffix": "tail1234.ts.net"}')
    out = io.StringIO()
    runner = DryRunRunner(inner, out)

    assert tailscale.tailnet_suffix(runner) == "tail1234.ts.net"
    runner.run(docker.kill("lab-run-zap"))

    assert inner.argvs() == [("tailscale", "status", "--json")]
    assert out.getvalue() == "would run: docker kill lab-run-zap\n"


def test_dry_run_never_shows_a_secret_value(tmp_path: Path) -> None:
    out = io.StringIO()
    command = docker.run_job(
        ["docker", "run", "--env", "API_KEY", "img:1"],
        secrets={"API_KEY": "sk-live-1234"},
        timeout=60,
        log=tmp_path / "log",
    )
    DryRunRunner(FakeRunner(), out).run(command)
    assert "sk-live-1234" not in out.getvalue()
    assert "API_KEY=<redacted>" in out.getvalue()


class Echo(BaseHTTPRequestHandler):
    """Answers every request with what it received, as JSON; 418 for /fail."""

    def do_GET(self) -> None:
        self._answer(b"")

    def do_POST(self) -> None:
        self._answer(self.rfile.read(int(self.headers["Content-Length"])))

    def _answer(self, body: bytes) -> None:
        form: dict[str, str] = {}
        if body:
            raw = f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode()
            for part in BytesParser(policy=HTTP).parsebytes(raw + body).iter_parts():
                payload = part.get_payload(decode=True)
                assert isinstance(payload, bytes)
                form[str(part.get_param("name", header="content-disposition"))] = (
                    payload.decode()
                )
        echoed = {
            "path": self.path,
            "authorization": self.headers["Authorization"],
            "form": form,
        }
        if self.path.startswith("/fail"):
            echoed["detail"] = f"rejected {self.headers['Authorization']}"
        status = 418 if self.path.startswith("/fail") else 200
        self.send_response(status)
        self.end_headers()
        self.wfile.write(json.dumps(echoed).encode())

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def echo_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_a_request_sends_query_header_form_and_file(
    echo_url: str, tmp_path: Path
) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"site": []}')
    request = HttpRequest(
        "POST",
        f"{echo_url}/api/import/",
        Effect.WRITE,
        query=(("status", "Open"), ("status", "In review")),
        headers={"Authorization": f"APIToken {TOKEN}"},
        # A value starting with @ is text, never a file to read.
        form={"service": "@semgrep"},
        file=("file", report),
    )
    echoed = json.loads(LiveRunner().request(request).body)
    assert echoed["path"] == "/api/import/?status=Open&status=In+review"
    assert echoed["authorization"] == f"APIToken {TOKEN}"
    assert echoed["form"] == {"service": "@semgrep", "file": '{"site": []}'}


def test_a_failed_request_shows_the_body_but_never_the_token(echo_url: str) -> None:
    request = HttpRequest(
        "GET",
        f"{echo_url}/fail",
        Effect.READ,
        headers={"Authorization": f"APIToken {TOKEN}"},
    )
    with pytest.raises(CommandError, match=r"HTTP 418[\s\S]*rejected") as err:
        LiveRunner().request(request)
    assert TOKEN not in str(err.value)
    assert "Authorization: <redacted>" in str(err.value)


def test_an_unreachable_host_is_an_error() -> None:
    # Port 9 (discard) on loopback: nothing listens there in CI or on a laptop.
    request = HttpRequest("GET", "http://127.0.0.1:9/", Effect.READ, timeout=2)
    with pytest.raises(CommandError, match=r"127\.0\.0\.1:9"):
        LiveRunner().request(request)


def test_dry_run_sends_reads_and_prints_writes(tmp_path: Path) -> None:
    inner, out = FakeRunner(), io.StringIO()
    inner.respond("GET", "/api/products/", body='{"results": []}')
    runner = DryRunRunner(inner, out)

    secobserve.get(runner, "https://so", TOKEN, "/api/products/")
    upload = secobserve.Upload(tmp_path / "report.json", service="zap-baseline")
    counts = secobserve.submit(runner, "https://so", TOKEN, upload)

    assert [r.method for r in inner.requests] == ["GET"]
    assert counts == secobserve.Counts(new=0, updated=0, resolved=0)
    printed = out.getvalue()
    assert printed.startswith("would send: POST https://so/api/import/")
    assert "service=zap-baseline" in printed
    assert TOKEN not in printed


# The effect labels are what keep --dry-run from doing anything. A command that
# changes something must say WRITE; this is the list to extend with each one.
def test_effects(tmp_path: Path) -> None:
    writes: list[Command | HttpRequest] = [
        docker.run_job(["docker", "run"], secrets={}, timeout=1, log=tmp_path / "l"),
        docker.kill("c"),
        docker.build(tmp_path, dockerfile=tmp_path / "D", target="prod", tag="t:1"),
        docker.save("t:1", tmp_path / "t.tar"),
        *git.checkout("0" * 40, tmp_path / "src"),
        secobserve.upload("https://so", TOKEN, secobserve.Upload(tmp_path, "j")),
    ]
    reads = [
        tailscale.status(),
        tailscale.ip4("pentest"),
        aws.get_parameter("/p", "us-east-1"),
        aws.get_secret("s", "us-east-1"),
        docker.inspect_image("t:1"),
    ]
    assert all(c.effect is Effect.WRITE for c in writes)
    assert all(c.effect is Effect.READ for c in reads)


def test_address_rejects_anything_but_an_ipv4() -> None:
    runner = FakeRunner()
    runner.on("tailscale", "ip", stdout="100.64.0.7\n")
    assert tailscale.address(runner, "pentest") == "100.64.0.7"
    runner.on("tailscale", "ip", stdout="no such host\n")
    with pytest.raises(CommandError, match="not an IPv4 address"):
        tailscale.address(runner, "pentest")


def test_a_program_off_path_is_found_where_it_was_searched_for(tmp_path: Path) -> None:
    # Tailscale's Mac App Store app is reachable only through a shell alias.
    program = tmp_path / "Tailscale"
    program.write_text('#!/bin/sh\necho found "$@"\n')
    program.chmod(0o755)
    command = Command(("no-such-program-xyz", "status"), Effect.READ, search=(program,))
    assert LiveRunner().run(command).stdout == "found status\n"


def test_a_missing_program_says_how_to_install_it() -> None:
    command = Command(
        ("no-such-program-xyz",),
        Effect.READ,
        install_hint="install it: https://example.com/download",
    )
    with pytest.raises(CommandError, match="not installed; install it: https"):
        LiveRunner().run(command)


def test_stream_yields_lines_as_they_come_and_stops_when_closed() -> None:
    # Prints one line, then would sleep for a minute: a follower that has
    # what it needs closes the stream, which must kill the command at once.
    code = "import sys, time; print('first', flush=True); time.sleep(60)"
    lines = LiveRunner().stream(python(code))
    assert next(lines) == "first\n"
    lines.close()


def test_stream_raises_on_failure_with_stderr() -> None:
    code = "import sys; print('out'); sys.stderr.write('lost\\n'); sys.exit(255)"
    with pytest.raises(CommandError, match=r"exited 255[\s\S]*lost"):
        list(LiveRunner().stream(python(code)))
