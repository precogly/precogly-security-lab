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


def compose_up(
    compose_file: Path, project: str, *, environment: Mapping[str, str]
) -> Command:
    """Start a job's stack and wait until its one-shot seed and backend are ready."""
    return Command(
        (
            "docker",
            "compose",
            "--file",
            str(compose_file),
            "--project-name",
            project,
            "up",
            "--detach",
            "--wait",
        ),
        Effect.WRITE,
        env=dict(environment),
        secret=frozenset({"POSTGRES_PASSWORD", "SECRET_KEY"}),
        timeout=15 * 60,
    )


def compose_down(
    compose_file: Path, project: str, *, environment: Mapping[str, str]
) -> Command:
    """Delete a job's stack, including its database volume and orphan containers."""
    return Command(
        (
            "docker",
            "compose",
            "--file",
            str(compose_file),
            "--project-name",
            project,
            "down",
            "--volumes",
            "--remove-orphans",
        ),
        Effect.WRITE,
        env=dict(environment),
        secret=frozenset({"POSTGRES_PASSWORD", "SECRET_KEY"}),
        timeout=5 * 60,
        check=False,
    )


def compose_logs(
    compose_file: Path,
    project: str,
    output: Path,
    *,
    environment: Mapping[str, str],
) -> Command:
    """Save the backend request log before the throwaway stack is removed."""
    return Command(
        (
            "docker",
            "compose",
            "--file",
            str(compose_file),
            "--project-name",
            project,
            "logs",
            "--no-color",
            "backend",
        ),
        Effect.WRITE,
        env=dict(environment),
        secret=frozenset({"POSTGRES_PASSWORD", "SECRET_KEY"}),
        timeout=60,
        check=False,
        output=output,
    )


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


def list_images(repository: str) -> Command:
    """Every tag of one local repository, a `repository:tag` per line."""
    return Command(
        (
            *("docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"),
            repository,
        ),
        Effect.READ,
        timeout=30,
    )


def remove_images(refs: list[str]) -> Command:
    # check=False: an image a stopped container still holds is left for the next
    # run, rather than failing this one.
    return Command(
        ("docker", "image", "rm", *refs), Effect.WRITE, timeout=120, check=False
    )
