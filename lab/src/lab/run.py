"""One run: jobs against a target, at the commit the instance deploys."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from lab import inputs
from lab.command import CommandRunner, CommandTimeout, aws, docker, fs, tailscale
from lab.container import Run, container_name, run_args
from lab.job import Job
from lab.target import Target

# Terraform's default region.
REGION = "us-east-1"
# Run directories, inputs and logs, on the scanner box.
ROOT = Path("/var/lib/lab")


def run_id(now: datetime, sha: str) -> str:
    """Sorts by time, and names the commit: 20261017T163000Z-94dd831."""
    return f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}-{sha[:7]}"


def assets_dir(job: Job) -> Path | None:
    """A job's assets ship inside the lab package, at lab/<assets>."""
    return Path(str(files("lab") / job.assets)) if job.assets else None


def execute(
    jobs: list[Job],
    target: Target,
    runner: CommandRunner,
    *,
    now: datetime,
    root: Path = ROOT,
    region: str = REGION,
) -> str:
    """Prepare the run and start each job's container. Returns the run ID.

    Through DryRunRunner this prints every change it would make, having read
    the real tailnet, target address and SHA.
    """
    tailnet = tailscale.tailnet_suffix(runner)
    host = target.host(tailnet)
    address = tailscale.address(runner, host)
    sha = aws.precogly_sha(runner, region)
    rid = run_id(now, sha)

    run_dir = root / "runs" / rid
    runner.run(fs.mkdir(run_dir))
    target_json = run_dir / "target.json"
    runner.run(fs.write_text(target_json, target.as_json(tailnet)))

    wanted = frozenset().union(*(job.inputs for job in jobs))
    prepared = inputs.prepare(runner, wanted, sha, root)

    for job in jobs:
        out_dir = run_dir / job.name
        runner.run(fs.mkdir(out_dir))
        run = Run(
            run_id=rid,
            precogly_sha=sha,
            target_url=target.url(tailnet),
            target_host=host,
            target_ip=address,
            out_dir=out_dir,
            target_json=target_json,
            inputs=prepared,
            assets_dir=assets_dir(job),
        )
        argv = run_args(job, run)
        # Read even on a dry run: it proves each secret exists and is readable,
        # and the value stays in memory, redacted wherever it would be shown.
        secrets = {
            env: aws.job_secret(runner, name, region)
            for name, env in job.secret_env.items()
        }
        command = docker.run_job(
            argv, secrets=secrets, timeout=job.timeout_seconds, log=out_dir / "job.log"
        )
        try:
            runner.run(command)
        except CommandTimeout:
            # The timeout killed the docker client, not the container.
            runner.run(docker.kill(container_name(job, run)))
            raise
    return rid
