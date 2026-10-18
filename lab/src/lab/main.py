"""The `lab` command: list jobs, and run them against the lab's Precogly."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from lab.command import CommandError, CommandRunner, DryRunRunner, LiveRunner
from lab.job import Job, JobError, load_jobs
from lab.run import Status, execute
from lab.target import TargetError, load_target

# The only target until a second exists, so `lab run` takes no --target.
TARGET = "pentest"


def _definitions(kind: str) -> Path:
    return Path(str(files("lab") / kind))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lab", description="Run scan jobs against the lab's Precogly instance."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("jobs", help="list jobs, and fail on any that do not load")
    run = commands.add_parser("run", help="run jobs, then reimport each report")
    run.add_argument("jobs", nargs="*", metavar="JOB", help="jobs to run, by name")
    run.add_argument("--all", action="store_true", help="run every job")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="read the real tailnet, address and commit; print every change; make none",
    )
    return parser


def _select(jobs: dict[str, Job], names: list[str], everything: bool) -> list[Job]:
    if everything == bool(names):
        raise JobError("name the jobs to run, or pass --all, not both")
    if everything:
        return list(jobs.values())
    if unknown := [n for n in names if n not in jobs]:
        raise JobError(f"no job named {unknown}; `lab jobs` lists them")
    return [jobs[n] for n in names]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        jobs = load_jobs(_definitions("jobs"))
        if args.command == "jobs":
            for job in jobs.values():
                inputs = ", ".join(sorted(job.inputs)) or "-"
                print(f"{job.name:<18} {job.report:<18} {inputs:<16} {job.image}")
            return 0

        selected = _select(jobs, args.jobs, args.all)
        target = load_target(_definitions("targets") / f"{TARGET}.toml")
        runner: CommandRunner = LiveRunner()
        if args.dry_run:
            runner = DryRunRunner(runner)
        rid, outcomes = execute(selected, target, runner, now=datetime.now(UTC))
        if args.dry_run:
            # The outcomes are what the dry run assumed, not results.
            print(f"dry run {rid}: nothing was changed")
            return 0
        for outcome in outcomes:
            c = outcome.observations
            counts = (
                f"{c.new} new, {c.updated} updated, {c.resolved} resolved" if c else ""
            )
            print(f"{outcome.job:<18} {outcome.status:<16} {counts}")
            if outcome.error:
                print(f"  {outcome.error}", file=sys.stderr)
        print(f"run {rid}")
        return 0 if all(o.status is Status.OK for o in outcomes) else 1
    except (JobError, TargetError, CommandError) as err:
        print(f"lab: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
