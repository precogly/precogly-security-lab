"""One run: jobs against a target, at the commit the instance deploys."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

import lab
from lab import inputs, sarif
from lab.command import (
    CommandError,
    CommandRunner,
    CommandTimeout,
    aws,
    docker,
    fs,
    secobserve,
    tailscale,
)
from lab.container import Run, built_image_ref, container_name, run_args
from lab.events import Event, event
from lab.job import Input, Job
from lab.target import Target

# Terraform's default region.
REGION = "us-east-1"
# Run directories, inputs and logs, on the scanner box.
ROOT = Path("/var/lib/lab")
# SecObserve's tailnet machine name.
SECOBSERVE_HOST = "secobserve"


class Status(StrEnum):
    OK = "ok"
    # The job ended without a non-empty report. Not uploaded.
    FAILED = "failed"
    TIMEOUT = "timeout"
    # The report exists but SecObserve did not take it.
    UPLOAD_FAILED = "upload-failed"


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
    # What SecObserve did with the upload: new, updated and resolved findings.
    observations: secobserve.Counts | None
    error: str | None


def run_id(now: datetime, sha: str) -> str:
    """Sorts by time, and names the commit: 20261017T163000Z-94dd831."""
    return f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}-{sha[:7]}"


def assets_dir(job: Job) -> Path | None:
    """A job's assets ship inside the lab package, at lab/<assets>."""
    return Path(str(files("lab") / job.assets)) if job.assets else None


def tool_version(job: Job) -> str:
    """The scanner's version for meta.json: the image tag, or lab's own."""
    if job.built_image:
        return f"lab {lab.__version__}"
    name = job.image.rsplit("/", 1)[-1]
    return name.split("@", 1)[1] if "@" in name else name.partition(":")[2]


def stack_project(run_id: str, job: str) -> str:
    """Compose project name, and therefore network prefix, for one job."""
    return f"lab-{run_id}-{job}".lower()


def _stack_environment(run_id: str, job: Job, sha: str) -> dict[str, str]:
    # These credentials protect only an internal, throwaway network. Deriving
    # them avoids persisting state while keeping dry runs reproducible.
    def credential(label: str) -> str:
        return hashlib.sha256(f"{run_id}:{job.name}:{label}".encode()).hexdigest()

    return {
        "BACKEND_IMAGE": built_image_ref("precogly-backend", sha),
        "POSTGRES_PASSWORD": credential("postgres"),
        "SECRET_KEY": credential("django"),
    }


def execute(
    jobs: list[Job],
    target: Target,
    runner: CommandRunner,
    *,
    now: datetime,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    root: Path = ROOT,
    region: str = REGION,
    on_event: Callable[[Event], None] = lambda _: None,
) -> tuple[str, list[Outcome]]:
    """Run each job, then upload each report that exists. Returns the run ID
    and one outcome per job.

    Through DryRunRunner this prints every change it would make, having read
    the real tailnet, target address and SHA. `on_event` is told of the run
    and of each job as it starts and ends; see `lab.events`.
    """
    tailnet = tailscale.tailnet_suffix(runner)
    host = target.host(tailnet)
    address = tailscale.address(runner, host)
    sha = aws.precogly_sha(runner, region)
    rid = run_id(now, sha)
    on_event(event("run", clock(), run=rid, precogly=sha, jobs=[j.name for j in jobs]))

    run_dir = root / "runs" / rid
    runner.run(fs.mkdir(run_dir))
    target_json = run_dir / "target.json"
    runner.run(fs.write_text(target_json, target.as_json(tailnet)))

    wanted = frozenset().union(*(job.inputs for job in jobs))
    inputs.prune(runner, sha, root)
    prepared = inputs.prepare(runner, wanted, sha, root)

    secobserve_url = f"https://{SECOBSERVE_HOST}.{tailnet}"
    token: str | None = None
    outcomes = []
    for job in jobs:
        out_dir = run_dir / job.name
        runner.run(fs.mkdir(out_dir))
        owns_stack = Input.STACK in job.inputs
        project = stack_project(rid, job.name)
        run = Run(
            run_id=rid,
            precogly_sha=sha,
            target_url="http://backend:8000" if owns_stack else target.url(tailnet),
            target_host="backend" if owns_stack else host,
            target_ip=address,
            out_dir=out_dir,
            target_json=target_json,
            inputs=prepared,
            assets_dir=assets_dir(job),
            network=f"{project}_stack" if owns_stack else "bridge",
        )
        started = clock()
        on_event(event("job_started", started, job=job.name))
        # Read even on a dry run: it proves each secret exists and is readable,
        # and the value stays in memory, redacted wherever it would be shown.
        secrets = {
            env: aws.job_secret(runner, name, region)
            for name, env in job.secret_env.items()
        }
        exit_code: int | None = None
        counts: secobserve.Counts | None = None
        error: str | None = None
        stack_file = Path(str(files("lab") / "stacks" / "precogly" / "compose.yml"))
        stack_env = _stack_environment(rid, job, sha)
        try:
            if owns_stack:
                runner.run(
                    docker.compose_up(
                        stack_file,
                        project,
                        environment=stack_env,
                    )
                )
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
                status = Status.OK
        finally:
            if owns_stack:
                runner.run(
                    docker.compose_logs(
                        stack_file,
                        project,
                        out_dir / "backend.log",
                        environment=stack_env,
                    )
                )
                runner.run(
                    docker.compose_down(stack_file, project, environment=stack_env)
                )

        if status is Status.OK:
            report = out_dir / job.report
            # An upload resolves every finding the report lacks, so a missing
            # or empty report must never be sent: it would resolve the job's
            # whole history.
            if not fs.non_empty(runner, report):
                status = Status.FAILED
                error = f"no report at {report}; see {out_dir / 'job.log'}"
            else:
                try:
                    if token is None:
                        token = aws.secobserve_token(runner, region)
                    counts = secobserve.submit(
                        runner,
                        secobserve_url,
                        token,
                        secobserve.Upload(
                            report=_for_upload(runner, job, report),
                            service=job.name,
                            docker_image=(
                                built_image_ref(job.scans_image, sha).removeprefix(
                                    "lab/"
                                )
                                if job.scans_image
                                else None
                            ),
                        ),
                    )
                except (CommandError, sarif.SarifError) as err:
                    status, error = Status.UPLOAD_FAILED, str(err)

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
            observations=counts,
            error=error,
        )
        meta = json.dumps(asdict(outcome), indent=2) + "\n"
        runner.run(fs.write_text(out_dir / "meta.json", meta))
        outcomes.append(outcome)
        on_event(
            event(
                "job_finished",
                clock(),
                job=job.name,
                status=str(status),
                observations=asdict(counts) if counts else None,
                error=error,
            )
        )
    ok = all(o.status is Status.OK for o in outcomes)
    on_event(event("run_finished", clock(), run=rid, ok=ok))
    return rid, outcomes


def _for_upload(runner: CommandRunner, job: Job, report: Path) -> Path:
    """The file to upload: SARIF with repository paths, or the report as is.

    SARIF from a source scan carries container paths (/in/precogly-source/...),
    and a finding whose path changes between runs counts as new.
    """
    if report.suffix != ".sarif":
        return report
    prepared = sarif.prepare(fs.read_text(runner, report), job.name)
    upload = report.with_name("upload.sarif")
    runner.run(fs.write_text(upload, json.dumps(prepared)))
    return upload
