"""A remote run: the lock, the start, and following its events to the end."""

from __future__ import annotations

import io
import json

import pytest
from rich.console import Console

from lab import remote
from lab.command.fake import FakeRunner
from lab.events import VERSION
from lab.progress import Display
from lab.remote import RemoteError

SHOW = ("ssh", "-o", "BatchMode=yes", remote.SCANNER)
RUNNING = (
    "ActiveState=active\n"
    "Description=lab-run 0123abcd started by alvin@laptop\n"
    "ActiveEnterTimestamp=Sun 2026-10-18 09:00:00 UTC\n"
    "MainPID=4242\n"
)
IDLE = "ActiveState=inactive\nDescription=lab-run.service\nMainPID=0\n"


def line(kind: str, **fields: object) -> str:
    return json.dumps({"type": kind, "at": "2026-10-18T09:00:00+00:00", **fields})


VERSION_LINE = line("version", events=VERSION, lab="b125f6c")


def test_a_run_in_progress_is_reported_with_how_to_attach() -> None:
    box = FakeRunner()
    box.on(*SHOW, stdout=RUNNING)
    running = remote.unit(box)
    assert (running.active, running.nonce, running.main_pid) == (True, "0123abcd", 4242)
    message = str(remote.busy(running))
    assert "started by alvin@laptop" in message
    assert "since Sun 2026-10-18 09:00:00 UTC" in message
    assert "lab run --remote --attach" in message


def test_start_runs_lab_as_the_locking_unit() -> None:
    box = FakeRunner()
    box.on(*SHOW, stdout=RUNNING)
    remote.start(box, "0123abcd", "alvin@laptop", ["--all"])

    [start] = [c for c in box.commands if "systemd-run" in c.argv[-1]]
    assert start.argv[-1] == (
        "sudo systemd-run --unit=lab-run --collect --property=KillMode=mixed "
        "--property=TimeoutStopSec=180 --uid=ubuntu "
        "'--description=lab-run 0123abcd started by alvin@laptop' "
        "/usr/local/bin/lab run --events /var/lib/lab/events/0123abcd.jsonl --all"
    )


def test_a_lost_race_to_start_is_the_lock() -> None:
    box = FakeRunner()
    box.on(*SHOW, stdout=RUNNING)
    # FakeRunner matches the remote command as one argv element.
    box.on(
        *SHOW,
        "sudo systemd-run --unit=lab-run --collect --property=KillMode=mixed "
        "--property=TimeoutStopSec=180 --uid=ubuntu "
        "'--description=lab-run feed started by me' "
        "/usr/local/bin/lab run --events /var/lib/lab/events/feed.jsonl semgrep",
        returncode=1,
    )
    with pytest.raises(RemoteError, match="already going"):
        remote.start(box, "feed", "me", ["semgrep"])


def test_follow_reads_to_the_last_event() -> None:
    box = FakeRunner()
    lines = [
        VERSION_LINE,
        line("run", run="r1", jobs=["semgrep"]),
        line("job_started", job="semgrep"),
        line("job_finished", job="semgrep", status="ok"),
        line("run_finished", run="r1", ok=True),
    ]
    box.streams(*SHOW, lines=lines)
    kinds = [e["type"] for e in remote.follow(box, "0123abcd", 4242)]
    assert kinds[-1] == "run_finished"
    [tail] = box.commands
    assert "--pid=4242" in tail.argv[-1]
    assert tail.timeout is None


def test_another_events_version_is_refused() -> None:
    box = FakeRunner()
    box.streams(*SHOW, lines=[line("version", events=VERSION + 1, lab="f00d")])
    with pytest.raises(RemoteError, match="install the same lab on both"):
        list(remote.follow(box, "0123abcd", 4242))


def test_a_run_that_dies_without_a_last_event_points_at_its_journal() -> None:
    box = FakeRunner()
    box.streams(*SHOW, lines=[VERSION_LINE, line("job_started", job="semgrep")])
    with pytest.raises(RemoteError, match="journalctl -u lab-run"):
        list(remote.follow(box, "0123abcd", 4242))


def test_a_dropped_connection_says_the_run_continues() -> None:
    box = FakeRunner()
    box.streams(*SHOW, lines=[VERSION_LINE], returncode=255)
    with pytest.raises(RemoteError, match="the run continues"):
        list(remote.follow(box, "0123abcd", 4242))


def test_an_idle_unit_has_no_nonce() -> None:
    box = FakeRunner()
    box.on(*SHOW, stdout=IDLE)
    idle = remote.unit(box)
    assert (idle.active, idle.nonce) == (False, None)


def test_off_a_terminal_each_job_is_a_line() -> None:
    out = io.StringIO()
    display = Display(Console(file=out, width=100))
    finished = json.loads(line("job_finished", job="semgrep", status="ok"))
    finished["at"] = "2026-10-18T09:01:12+00:00"
    finished["observations"] = {"new": 0, "updated": 36, "resolved": 0}
    for text in [
        line("run", run="r1", precogly="94dd831e", jobs=["semgrep", "zap"]),
        line("job_started", job="semgrep"),
        json.dumps(finished),
        line("job_started", job="zap"),
        line("job_finished", job="zap", status="timeout", error="timed out\nmore"),
    ]:
        display.handle(json.loads(text))
    display.close()
    assert out.getvalue().splitlines() == [
        "run r1, Precogly at 94dd831",
        "  started  semgrep",
        "  ✓ semgrep          ok · 36 updated (1m12s)",
        "  started  zap",
        "  ✗ zap              timeout · timed out (0m00s)",
    ]


def test_stop_needs_a_run_in_progress() -> None:
    box = FakeRunner()
    box.on(*SHOW, stdout=IDLE)
    with pytest.raises(RemoteError, match="no run is in progress"):
        remote.stop(box)


def test_stop_waits_for_systemd_and_says_whose_run_it_was() -> None:
    box = FakeRunner()
    box.on(*SHOW, stdout=RUNNING)
    stopped = remote.stop(box)
    assert "started by alvin@laptop" in stopped.description
    [stop] = [c for c in box.commands if "systemctl stop" in c.argv[-1]]
    assert stop.argv[-1] == "sudo systemctl stop lab-run"
    # Outlasts TimeoutStopSec, so a slow cleanup is not reported as a failure.
    assert stop.timeout is not None and stop.timeout > 180


def test_leftovers_are_lab_s_alone() -> None:
    box = FakeRunner()
    box.on(
        *SHOW,
        stdout=(
            "container lab-20261018t194134z-94dd831-schemathesis\n"
            "network lab-20261018t194134z-94dd831-schemathesis_stack\n"
            "volume 3f2a lab-20261018t194134z-94dd831-schemathesis\n"
            "volume 9c1b someone-elses-project\n"
        ),
    )
    assert remote.leftovers(box) == [
        "container lab-20261018t194134z-94dd831-schemathesis",
        "network lab-20261018t194134z-94dd831-schemathesis_stack",
        "volume 3f2a lab-20261018t194134z-94dd831-schemathesis",
    ]
