"""The `lab` command: list jobs, and run them against the lab's Precogly."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer

from lab.command import CommandError, CommandRunner, DryRunRunner, LiveRunner
from lab.job import Job, JobError, load_jobs
from lab.run import Status, execute
from lab.target import TargetError, load_target

# The only target until a second exists, so `lab run` takes no --target.
TARGET = "pentest"

app = typer.Typer(
    help="Run scan jobs against the lab's Precogly instance.",
    no_args_is_help=True,
    add_completion=False,
    # A traceback's locals can hold a token; never print them.
    pretty_exceptions_show_locals=False,
)


def _definitions(kind: str) -> Path:
    return Path(str(files("lab") / kind))


def _select(jobs: dict[str, Job], names: list[str], everything: bool) -> list[Job]:
    if everything == bool(names):
        raise JobError("name the jobs to run, or pass --all, not both")
    if everything:
        return list(jobs.values())
    if unknown := [n for n in names if n not in jobs]:
        raise JobError(f"no job named {unknown}; `lab jobs` lists them")
    return [jobs[n] for n in names]


@app.command("jobs")
def list_jobs() -> None:
    """List jobs, and fail on any that do not load."""
    for job in load_jobs(_definitions("jobs")).values():
        inputs = ", ".join(sorted(job.inputs)) or "-"
        print(f"{job.name:<18} {job.report:<18} {inputs:<16} {job.image}")


@app.command()
def run(
    names: Annotated[
        list[str] | None, typer.Argument(metavar="JOB...", help="Jobs to run, by name.")
    ] = None,
    everything: Annotated[bool, typer.Option("--all", help="Run every job.")] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Read the real tailnet, address and commit; print every change; "
            "make none.",
        ),
    ] = False,
) -> None:
    """Run jobs, then upload each report to SecObserve."""
    selected = _select(load_jobs(_definitions("jobs")), names or [], everything)
    target = load_target(_definitions("targets") / f"{TARGET}.toml")
    runner: CommandRunner = LiveRunner()
    if dry_run:
        runner = DryRunRunner(runner)
    rid, outcomes = execute(selected, target, runner, now=datetime.now(UTC))
    if dry_run:
        # The outcomes are what the dry run assumed, not results.
        print(f"dry run {rid}: nothing was changed")
        return
    for outcome in outcomes:
        c = outcome.observations
        counts = f"{c.new} new, {c.updated} updated, {c.resolved} resolved" if c else ""
        print(f"{outcome.job:<18} {outcome.status:<16} {counts}")
        if outcome.error:
            print(f"  {outcome.error}", file=sys.stderr)
    print(f"run {rid}")
    if not all(o.status is Status.OK for o in outcomes):
        raise typer.Exit(1)


def main(argv: list[str] | None = None) -> int:
    try:
        app(args=argv, prog_name="lab")
    except SystemExit as done:
        return done.code if isinstance(done.code, int) else 0
    except (JobError, TargetError, CommandError) as err:
        print(f"lab: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
