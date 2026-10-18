"""The `docker run` a job gets: the same interface for every job."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lab.job import Input, Job


@dataclass(frozen=True)
class Run:
    """Everything about one run that a job's container sees."""

    run_id: str
    precogly_sha: str
    target_url: str
    target_host: str
    # The target's tailnet address. Containers are on Docker's bridge network
    # and do not see MagicDNS, so the host is pinned to it with --add-host.
    target_ip: str
    out_dir: Path
    target_json: Path
    inputs: dict[Input, Path]
    assets_dir: Path | None
    # Set for a job with precogly-stack. Its scanner joins this internal network
    # and targets the backend service, rather than the shared lab instance.
    network: str = "bridge"


def built_image_ref(name: str, sha: str) -> str:
    """The local tag lab gives a built image, one per commit."""
    return f"lab/{name}:{sha}"


def container_name(job: Job, run: Run) -> str:
    """Unique per job per run, so a timed-out container can be killed by name."""
    return f"lab-{run.run_id}-{job.name}".lower()


def run_args(job: Job, run: Run) -> list[str]:
    """The full `docker run` command for `job` in `run`.

    Secrets appear by variable name only (`--env NAME`): Docker reads the value
    from the environment lab runs it in, so no value reaches the command line,
    `ps`, or anything --dry-run prints.
    """
    placeholders = {
        "target_url": run.target_url,
        "precogly_sha": run.precogly_sha,
        "run_id": run.run_id,
    }
    image = (
        built_image_ref(job.built_image, run.precogly_sha)
        if job.built_image
        else job.image
    )

    args = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name(job, run),
        # Never --network host. With the box's metadata hop limit at 1, a bridge
        # container cannot reach the metadata service, so cannot take the box's
        # role, which can read lab's SecObserve upload token.
        "--network",
        run.network,
    ]
    if run.network == "bridge":
        # On a stack network Docker DNS resolves `backend`; an /etc/hosts entry
        # would override it with the shared instance's tailnet address.
        args += ["--add-host", f"{run.target_host}:{run.target_ip}"]
    if job.entrypoint:
        args += ["--entrypoint", job.entrypoint]
    args += [
        "--volume",
        f"{run.out_dir}:{job.out_mount}",
        "--volume",
        f"{run.target_json}:/run/lab/target.json:ro",
    ]
    for name in sorted(job.inputs):
        if name is Input.STACK:
            continue
        args += ["--volume", f"{run.inputs[name]}:/in/{name}:ro"]
    if job.assets:
        if run.assets_dir is None:
            raise ValueError(f"job {job.name} has assets but the run has none")
        args += ["--volume", f"{run.assets_dir}:/job:ro"]
    for key, value in (
        ("TARGET_URL", run.target_url),
        ("PRECOGLY_SHA", run.precogly_sha),
        ("RUN_ID", run.run_id),
        ("OUT_DIR", job.out_mount),
    ):
        args += ["--env", f"{key}={value}"]
    for env_name in job.secret_env.values():
        args += ["--env", env_name]

    args.append(image)
    args += [arg.format(**placeholders) for arg in job.command]
    return args
