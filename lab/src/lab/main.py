"""The `lab` command: list jobs, run them against the lab's Precogly, and export
their findings."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import keyring
import typer
from keyring.errors import KeyringError

from lab import auth, findings
from lab.auth import AuthError
from lab.command import (
    CommandError,
    CommandRunner,
    DryRunRunner,
    HttpError,
    LiveRunner,
    secobserve,
    tailscale,
)
from lab.findings import FindingsError, StatusChoice
from lab.job import Job, JobError, load_jobs
from lab.run import SECOBSERVE_HOST, Status, execute
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
auth_app = typer.Typer(
    help="Log in to SecObserve: mint, show, or revoke this machine's token.",
    no_args_is_help=True,
)
app.add_typer(auth_app, name="auth")


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


@app.command("findings")
def export_findings(
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write here, not stdout.")
    ] = None,
    job: Annotated[
        str | None, typer.Option("--job", help="One job's findings, by name.")
    ] = None,
    status: Annotated[
        list[StatusChoice] | None,
        typer.Option(
            "--status",
            help="active (the default), all but resolved, or one status; repeatable.",
        ),
    ] = None,
) -> None:
    """Export findings from SecObserve as JSON."""
    # A misspelt job would otherwise look like one that never uploaded.
    if job and job not in load_jobs(_definitions("jobs")):
        raise JobError(f"no job named {job!r}; `lab jobs` lists them")
    runner = LiveRunner()
    url = _secobserve_url(runner)
    now = datetime.now(UTC)
    doc = findings.export(
        runner,
        url,
        auth.token(keyring, url, os.environ, now.date()),
        findings.statuses(status or []),
        job,
        now,
        note=lambda text: print(f"lab: {text}", file=sys.stderr),
    )
    text = json.dumps(doc, indent=2) + "\n"
    if output:
        output.write_text(text)
        print(f"{len(doc['findings'])} findings to {output}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def _secobserve_url(runner: CommandRunner) -> str:
    return f"https://{SECOBSERVE_HOST}.{tailscale.tailnet_suffix(runner)}"


def _password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    elif sys.stdin.isatty():
        password = typer.prompt("SecObserve password", hide_input=True)
    else:
        raise AuthError("no terminal to ask for the password: pass --password-stdin")
    if not password:
        raise AuthError("the password is empty")
    return password


PasswordStdin = Annotated[
    bool,
    typer.Option("--password-stdin", help="Read the password from stdin."),
]


@auth_app.command("login")
def auth_login(
    username: Annotated[
        str | None, typer.Option("--username", "-u", help="Your SecObserve username.")
    ] = None,
    password_stdin: PasswordStdin = False,
) -> None:
    """Check the tailnet and SecObserve, then mint and store a token."""
    runner = LiveRunner()
    # Checked before asking for anything, so a network problem is not reported
    # as a failed login.
    url = _secobserve_url(runner)
    secobserve.health(runner, url)
    if username is None:
        if not sys.stdin.isatty():
            raise AuthError("no terminal to ask for the username: pass --username")
        username = typer.prompt("SecObserve username")
    password = _password(password_stdin)
    try:
        credential = auth.login(
            runner, keyring, url, username, password, datetime.now(UTC).date()
        )
    except KeyringError as err:
        raise AuthError(
            f"no system keyring to keep the token in ({err}); set {auth.ENV} instead"
        ) from None
    print(
        f"✓ Logged in to {url} as {credential.user}; token expires {credential.expires}"
    )


@auth_app.command("status")
def auth_status() -> None:
    """Show where tailscale is, whether SecObserve answers, and the token."""
    runner = LiveRunner()
    print(f"tailscale   {tailscale.location() or 'not found'}")
    url = _secobserve_url(runner)
    secobserve.health(runner, url)
    print(f"secobserve  {url} answers")
    if os.environ.get(auth.ENV):
        source = f"{auth.ENV}"
    else:
        credential = auth.stored(keyring, url)
        if credential is None:
            raise AuthError(f"not logged in to {url}. {auth.LOGIN}")
        source = f"keyring, {credential.user}, expires {credential.expires}"
    token = auth.token(keyring, url, os.environ, datetime.now(UTC).date())
    # Any authenticated read shows whether SecObserve still takes the token.
    secobserve.get(runner, url, token, "/api/products/", [("page_size", "1")])
    print(f"token       {source}; accepted")


@auth_app.command("logout")
def auth_logout(password_stdin: PasswordStdin = False) -> None:
    """Revoke this machine's token in SecObserve, then forget it."""
    runner = LiveRunner()
    url = _secobserve_url(runner)
    if auth.stored(keyring, url) is None:
        raise AuthError(f"not logged in to {url}")
    credential = auth.logout(runner, keyring, url, _password(password_stdin))
    print(
        f"✓ Logged out of {url}; {credential.user}'s token for this machine is revoked"
    )


def main(argv: list[str] | None = None) -> int:
    try:
        app(args=argv, prog_name="lab")
    except SystemExit as done:
        return done.code if isinstance(done.code, int) else 0
    except HttpError as err:
        print(f"lab: {auth.rejected(err) or err}", file=sys.stderr)
        return 1
    except (JobError, TargetError, CommandError, FindingsError, AuthError) as err:
        print(f"lab: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
