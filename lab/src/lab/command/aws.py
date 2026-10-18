"""Reading the values Terraform publishes, through the AWS CLI.

The CLI rather than boto3: it is already on the scanner box, and two reads do
not justify a dependency.
"""

from __future__ import annotations

from lab.command.core import Command, CommandRunner, Effect

PROJECT = "precogly-seclab"


def get_parameter(name: str, region: str) -> Command:
    return Command(
        (
            *("aws", "ssm", "get-parameter", "--region", region, "--name", name),
            *("--query", "Parameter.Value", "--output", "text"),
        ),
        Effect.READ,
        timeout=30,
    )


def get_secret(secret_id: str, region: str) -> Command:
    # The value comes back on stdout, which is never logged; the command line
    # names the secret only.
    return Command(
        (
            *("aws", "secretsmanager", "get-secret-value", "--region", region),
            *("--secret-id", secret_id, "--query", "SecretString", "--output", "text"),
        ),
        Effect.READ,
        timeout=30,
    )


def parameter(runner: CommandRunner, name: str, region: str) -> str:
    return runner.run(get_parameter(name, region)).stdout.strip()


def secret(runner: CommandRunner, secret_id: str, region: str) -> str:
    return runner.run(get_secret(secret_id, region)).stdout.rstrip("\n")


def precogly_sha(runner: CommandRunner, region: str) -> str:
    """The commit the instance deploys; only Terraform writes it."""
    return parameter(runner, f"/{PROJECT}/precogly-sha", region)


def job_secret(runner: CommandRunner, name: str, region: str) -> str:
    return secret(runner, f"{PROJECT}/jobs/{name}", region)


def secobserve_token(runner: CommandRunner, region: str) -> str:
    """lab's SecObserve upload token (Upload role), written by the SecObserve box."""
    return secret(runner, f"{PROJECT}/secobserve-upload-token", region)
