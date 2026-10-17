"""Commands, runners, and the effect each tool's commands declare."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from lab.command import (
    Command,
    CommandError,
    DryRunRunner,
    Effect,
    SubprocessRunner,
    aws,
    docker,
    git,
    tailscale,
)
from lab.command.fake import FakeRunner


def python(code: str, **kwargs: object) -> Command:
    return Command((sys.executable, "-c", code), Effect.READ, **kwargs)  # type: ignore[arg-type]


def test_runs_and_captures() -> None:
    result = SubprocessRunner().run(python("print('hello')"))
    assert (result.returncode, result.stdout) == (0, "hello\n")


def test_failure_names_the_command_and_its_stderr() -> None:
    code = "import sys; sys.stderr.write('boom\\n'); sys.exit(3)"
    with pytest.raises(CommandError, match=r"exited 3[\s\S]*boom"):
        SubprocessRunner().run(python(code))


def test_check_false_returns_the_failure() -> None:
    result = SubprocessRunner().run(python("raise SystemExit(2)", check=False))
    assert result.returncode == 2


def test_missing_program_and_timeout_are_actionable() -> None:
    with pytest.raises(CommandError, match="not installed"):
        SubprocessRunner().run(Command(("no-such-program-xyz",), Effect.READ))
    with pytest.raises(CommandError, match=r"timed out after 0\.2s"):
        SubprocessRunner().run(python("import time; time.sleep(5)", timeout=0.2))


def test_output_streams_to_a_file(tmp_path: Path) -> None:
    log = tmp_path / "run" / "job.log"
    code = "import sys; print('out'); sys.stderr.write('err\\n')"
    result = SubprocessRunner().run(python(code, output=log))
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
        SubprocessRunner().run(command)
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


# The effect labels are what keep --dry-run from doing anything. A command that
# changes something must say WRITE; this is the list to extend with each one.
def test_effects(tmp_path: Path) -> None:
    writes = [
        docker.run_job(["docker", "run"], secrets={}, timeout=1, log=tmp_path / "l"),
        docker.kill("c"),
        docker.build(tmp_path, dockerfile=tmp_path / "D", target="prod", tag="t:1"),
        docker.save("t:1", tmp_path / "t.tar"),
        *git.checkout("0" * 40, tmp_path / "src"),
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
