"""Running jobs on the scanner box from a laptop, and following them there.

The run is the transient systemd unit `lab-run` on the box, so it outlives the
SSH connection that started it, and the unit's name is the lock: systemd will
not start a second unit of the same name. The run writes its events to a file
the laptop names, and the laptop follows the file over SSH:

```text
laptop                               scanner box
------                               -----------
systemctl show lab-run      ---->    no run in progress
sudo systemd-run --unit lab-run ->   lab run --events /var/lib/lab/events/<nonce>.jsonl
tail -n +1 -F --pid=<lab's pid> <-   one JSON line per job started and finished
```

`tail -F` waits for a file that does not exist yet, and `--pid` ends it when
lab exits, so a run that dies without a last event ends the stream instead of
hanging it. The nonce is in the unit's description, which is how `--attach`
finds the file of a run it did not start.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import PurePosixPath

from lab.command import Command, CommandError, CommandRunner, Effect
from lab.events import VERSION, Event

# Tailscale SSH, as the user lab runs as on the box.
SCANNER = "ubuntu@scanner"
UNIT = "lab-run"
EVENTS = PurePosixPath("/var/lib/lab/events")
ATTACH = "lab run --remote --attach"
JOURNAL = f"ssh {SCANNER} journalctl -u {UNIT}"


class RemoteError(RuntimeError):
    """The scanner box's run could not be started or followed."""


def ssh(
    *remote: str, effect: Effect = Effect.READ, timeout: float | None = 60
) -> Command:
    # BatchMode: fail rather than prompt, since nothing reads a prompt here.
    return Command(
        ("ssh", "-o", "BatchMode=yes", SCANNER, shlex.join(remote)),
        effect,
        timeout=timeout,
    )


@dataclass(frozen=True)
class Unit:
    """The `lab-run` unit, as systemd reports it."""

    active: bool
    description: str
    since: str
    main_pid: int

    @property
    def nonce(self) -> str | None:
        """The events file's name, from `lab-run <nonce> started by ...`."""
        parts = self.description.split()
        return parts[1] if len(parts) > 1 and parts[0] == UNIT else None


def unit(runner: CommandRunner) -> Unit:
    out = runner.run(
        ssh(
            "systemctl",
            "show",
            UNIT,
            "--property=ActiveState,Description,ActiveEnterTimestamp,MainPID",
        )
    ).stdout
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return Unit(
        active=props.get("ActiveState") in ("active", "activating"),
        description=props.get("Description", ""),
        since=props.get("ActiveEnterTimestamp", ""),
        main_pid=int(props.get("MainPID") or 0),
    )


def busy(running: Unit) -> RemoteError:
    return RemoteError(
        f"a run is already going on the scanner box: {running.description}, "
        f"since {running.since}.\n  attach with: {ATTACH}"
    )


def events_file(nonce: str) -> PurePosixPath:
    return EVENTS / f"{nonce}.jsonl"


def start(runner: CommandRunner, nonce: str, who: str, selection: list[str]) -> Unit:
    """Start `lab run` on the box as `lab-run`, and return the unit."""
    command = ssh(
        "sudo",
        "systemd-run",
        f"--unit={UNIT}",
        # A failed unit is unloaded too, so it does not hold the lock.
        "--collect",
        # SIGTERM to lab alone, which then stops its job in order (`lab.run.
        # stop_on_sigterm`). By default systemd signals every process at once,
        # and `docker run` would forward it to the container mid-cleanup.
        "--property=KillMode=mixed",
        # Arbitrary: room to kill a container and take a stack down before
        # SIGKILL. Too short and the stack is left behind.
        "--property=TimeoutStopSec=180",
        "--uid=ubuntu",
        f"--description={UNIT} {nonce} started by {who}",
        "/usr/local/bin/lab",
        "run",
        "--events",
        str(events_file(nonce)),
        *selection,
        effect=Effect.WRITE,
    )
    try:
        runner.run(command)
    except CommandError:
        # Lost a race with another start: report it as the lock it is.
        running = unit(runner)
        if running.active:
            raise busy(running) from None
        raise
    return unit(runner)


def stop(runner: CommandRunner) -> Unit:
    """Stop the run in progress, waiting until lab has cleaned up and exited.

    Returns the unit as it was, to say whose run was stopped.
    """
    running = unit(runner)
    if not running.active:
        raise RemoteError("no run is in progress on the scanner box")
    # systemctl stop waits for the unit to end: lab's cleanup, or SIGKILL after
    # TimeoutStopSec, so the SSH timeout must outlast it.
    runner.run(ssh("sudo", "systemctl", "stop", UNIT, effect=Effect.WRITE, timeout=300))
    return running


def leftovers(runner: CommandRunner) -> list[str]:
    """Containers, networks and Compose volumes a run left on the box.

    Every job container and stack is named `lab-<run>-...`, and runs go one at a
    time, so anything of that name is a stop or crash that was not cleaned up.
    """
    script = (
        "docker ps -a --filter name=^lab- --format 'container {{.Names}}'; "
        "docker network ls --filter name=^lab- --format 'network {{.Name}}'; "
        "docker volume ls --filter label=com.docker.compose.project "
        "--format 'volume {{.Name}} {{.Label \"com.docker.compose.project\"}}'"
    )
    out = runner.run(ssh("sh", "-c", script)).stdout
    found = []
    for line in out.splitlines():
        # A volume line names its Compose project last; keep lab's only.
        if line.startswith("volume ") and not line.rsplit(" ", 1)[-1].startswith(
            "lab-"
        ):
            continue
        if line.strip():
            found.append(line.strip())
    return found


def follow(runner: CommandRunner, nonce: str, main_pid: int) -> Generator[Event]:
    """Yield the run's events from the first, until its last.

    Raises if the box's lab writes another version of the events, or if the
    stream ends with no last event.
    """
    path = str(events_file(nonce))
    # No timeout: followed for as long as the run takes.
    if main_pid:
        command = ssh("tail", "-n", "+1", "-F", f"--pid={main_pid}", path, timeout=None)
    else:
        # lab has already exited, so its file is complete, if it exists.
        command = ssh("cat", path, timeout=None)
    lines = runner.stream(command)
    try:
        for number, line in enumerate(lines):
            try:
                item: Event = json.loads(line)
            except ValueError:
                raise RemoteError(f"not an event: {line[:200]!r}") from None
            if number == 0:
                _check_version(item)
            yield item
            if item.get("type") in ("run_finished", "failed"):
                return
    except CommandError as err:
        raise RemoteError(
            f"lost the scanner box ({err}).\n  the run continues; attach with: {ATTACH}"
        ) from None
    finally:
        lines.close()
    raise RemoteError(f"the run ended without finishing; see: {JOURNAL}")


def _check_version(item: Event) -> None:
    if item.get("type") != "version" or item.get("events") != VERSION:
        raise RemoteError(
            f"the scanner box's lab (at {item.get('lab', 'unknown')}) writes events "
            f"version {item.get('events')}, and this lab reads version {VERSION}; "
            "install the same lab on both (docs/setup.md, step 5)"
        )
