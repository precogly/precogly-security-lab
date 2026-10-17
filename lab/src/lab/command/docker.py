"""Docker commands: running jobs, and building and saving Precogly's images."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from lab.command.core import Command, CommandRunner, Effect


def run_job(
    argv: list[str],
    *,
    secrets: Mapping[str, str],
    timeout: float,
    log: Path,
) -> Command:
    """A job's container, from `lab.container.run_args`.

    `secrets` maps each env name to its value. The values go into the
    environment of the `docker` process, which passes them on to the container
    for each `--env NAME`, and are named as secret so they are never shown.
    """
    return Command(
        tuple(argv),
        Effect.WRITE,
        env=dict(secrets),
        secret=frozenset(secrets),
        timeout=timeout,
        check=False,
        output=log,
    )


def kill(name: str) -> Command:
    # check=False: the container may already have exited.
    return Command(("docker", "kill", name), Effect.WRITE, timeout=30, check=False)


def inspect_image(ref: str) -> Command:
    return Command(
        ("docker", "image", "inspect", "--format", "{{.Id}}", ref),
        Effect.READ,
        timeout=30,
        check=False,
    )


def build(context: Path, *, dockerfile: Path, target: str, tag: str) -> Command:
    return Command(
        (
            *("docker", "build", "--file", str(dockerfile), "--target", target),
            *("--tag", tag, str(context)),
        ),
        Effect.WRITE,
    )


def save(ref: str, path: Path) -> Command:
    return Command(("docker", "save", "--output", str(path), ref), Effect.WRITE)


def image_exists(runner: CommandRunner, ref: str) -> bool:
    return runner.run(inspect_image(ref)).returncode == 0
