"""One run: jobs against a target, at the commit the instance deploys."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

import lab
from lab import inputs
from lab.command import (
    CommandError,
    CommandRunner,
    CommandTimeout,
    aws,
    defectdojo,
    docker,
    fs,
    tailscale,
)
from lab.container import Run, container_name, run_args
from lab.job import Job
from lab.target import Target

# Terraform's default region.
REGION = "us-east-1"
# Run directories, inputs and logs, on the scanner box.
ROOT = Path("/var/lib/lab")
# DefectDojo's tailnet machine name.
DEFECTDOJO_HOST = "defectdojo"


class Status(StrEnum):
    OK = "ok"
    # The job ended without a non-empty report. Not reimported.
    FAILED = "failed"
    TIMEOUT = "timeout"
    # The report exists but DefectDojo did not take it.
    REIMPORT_FAILED = "reimport-failed"


@dataclass(frozen=True)
class Outcome:
    """What one job did in one run; written to its meta.json."""

    job: str
    image: str
    version: str
    precogly_sha: str
    run_id: str
    started: str
    finished: str
    status: Status
    # The container's exit code, recorded only: scanners exit non-zero when
    # they find something, so success is judged by the report.
    exit_code: int | None
    test_id: int | None
    error: str | None


def run_id(now: datetime, sha: str) -> str:
    """Sorts by time, and names the commit: 20261017T163000Z-94dd831."""
    return f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}-{sha[:7]}"


def assets_dir(job: Job) -> Path | None:
    """A job's assets ship inside the lab package, at lab/<assets>."""
    return Path(str(files("lab") / job.assets)) if job.assets else None


def tool_version(job: Job) -> str:
    """What DefectDojo records as the version: the image tag, or lab's own."""
    if job.built_image:
        return f"lab {lab.__version__}"
    name = job.image.rsplit("/", 1)[-1]
    return name.split("@", 1)[1] if "@" in name else name.partition(":")[2]


def execute(
    jobs: list[Job],
    target: Target,
    runner: CommandRunner,
    *,
    now: datetime,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    root: Path = ROOT,
    region: str = REGION,
) -> tuple[str, list[Outcome]]:
    """Run each job, then reimport each report that exists. Returns the run ID
    and one outcome per job.

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

    defectdojo_url = f"https://{DEFECTDOJO_HOST}.{tailnet}"
    token: str | None = None
    outcomes = []
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
        started = clock()
        # Read even on a dry run: it proves each secret exists and is readable,
        # and the value stays in memory, redacted wherever it would be shown.
        secrets = {
            env: aws.job_secret(runner, name, region)
            for name, env in job.secret_env.items()
        }
        exit_code: int | None = None
        test_id: int | None = None
        error: str | None = None
        try:
            exit_code = runner.run(
                docker.run_job(
                    run_args(job, run),
                    secrets=secrets,
                    timeout=job.timeout_seconds,
                    log=out_dir / "job.log",
                )
            ).returncode
        except CommandTimeout as err:
            # The timeout killed the docker client, not the container.
            runner.run(docker.kill(container_name(job, run)))
            status, error = Status.TIMEOUT, str(err)
        else:
            report = out_dir / job.report
            # Reimport closes every finding the report lacks, so a missing or
            # empty report must never be sent: it would close the Test's
            # whole history.
            if not fs.non_empty(runner, report):
                status = Status.FAILED
                error = f"no report at {report}; see {out_dir / 'job.log'}"
            else:
                try:
                    if token is None:
                        token = aws.defectdojo_token(runner, region)
                    test_id = defectdojo.submit(
                        runner,
                        defectdojo_url,
                        token,
                        defectdojo.Reimport(
                            scan_type=job.scan_type,
                            report=report,
                            test_title=job.name,
                            commit_hash=sha,
                            build_id=rid,
                            version=tool_version(job),
                            scan_date=now.astimezone(UTC).date(),
                        ),
                    )
                    status = Status.OK
                except CommandError as err:
                    status, error = Status.REIMPORT_FAILED, str(err)

        outcome = Outcome(
            job=job.name,
            image=job.image,
            version=tool_version(job),
            precogly_sha=sha,
            run_id=rid,
            started=started.isoformat(),
            finished=clock().isoformat(),
            status=status,
            exit_code=exit_code,
            test_id=test_id,
            error=error,
        )
        meta = json.dumps(asdict(outcome), indent=2) + "\n"
        runner.run(fs.write_text(out_dir / "meta.json", meta))
        outcomes.append(outcome)
    return rid, outcomes
