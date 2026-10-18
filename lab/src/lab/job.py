"""Job definitions: one TOML file per scanner, validated when loaded."""

from __future__ import annotations

import re
import string
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any


class Input(StrEnum):
    """What lab builds from Precogly at the run's commit, once per run."""

    SOURCE = "precogly-source"
    IMAGES = "precogly-images"
    # A throwaway Precogly of the job's own, which the job targets instead of the
    # instance (lab.stack). Not mounted: the job reaches it over its network.
    STACK = "precogly-stack"


# Images built from Input.IMAGES, usable as a job's image with "@".
BUILT_IMAGES = frozenset({"precogly-backend", "precogly-frontend"})

# The only placeholders a command may use.
PLACEHOLDERS = frozenset({"target_url", "precogly_sha", "run_id"})

# Environment every job gets; a secret may not shadow one.
RESERVED_ENV = frozenset({"TARGET_URL", "PRECOGLY_SHA", "RUN_ID", "OUT_DIR"})

# Arbitrary. Long enough for a full ZAP scan; a job that needs more says so.
DEFAULT_TIMEOUT = "1h"
# Arbitrary ceiling, so a typo like "300h" fails at load instead of hanging a box.
MAX_TIMEOUT_SECONDS = 12 * 3600

# Where a job's run directory is mounted, unless the tool insists on its own:
# zap-baseline.py writes every report under /zap/wrk and exits 3 if that is not
# mounted (zap-baseline.py at v2.17.0, lines 302-309).
DEFAULT_OUT_MOUNT = "/out"
# Mount points lab already uses inside every container.
_TAKEN_MOUNTS = ("/in", "/job", "/run/lab")

_SECRET_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DURATION = re.compile(r"([1-9][0-9]*)([smh])")

_FIELDS = frozenset(
    {
        "name",
        "image",
        "command",
        "report",
        "scans_image",
        "inputs",
        "assets",
        "secrets",
        "timeout",
        "out_mount",
        "entrypoint",
    }
)
# No parser name: SecObserve detects the parser from the report itself.
_REQUIRED = frozenset({"name", "image", "command", "report"})


class JobError(ValueError):
    """A job definition that cannot be run."""


@dataclass(frozen=True)
class Job:
    name: str
    image: str
    command: tuple[str, ...]
    report: str
    # The built image this job scans, if any, so SecObserve labels its findings
    # with that image and the commit it was built from.
    scans_image: str | None
    inputs: frozenset[Input]
    assets: str | None
    # Names under precogly-seclab/jobs/ in Secrets Manager.
    secrets: tuple[str, ...]
    timeout_seconds: int
    # Where the run directory is mounted; the report is relative to it.
    out_mount: str
    # Override an image's ENTRYPOINT when an asset wrapper must orchestrate it.
    entrypoint: str | None = None

    @property
    def built_image(self) -> str | None:
        """The built image this job runs in, or None for a registry image."""
        return self.image.removeprefix("@") if self.image.startswith("@") else None

    @property
    def secret_env(self) -> dict[str, str]:
        """Secret name to the environment variable the job reads it from."""
        return {name: secret_env_name(name) for name in self.secrets}


def secret_env_name(secret: str) -> str:
    """The env var a secret is passed in: anthropic-api-key, ANTHROPIC_API_KEY."""
    return secret.upper().replace("-", "_")


def load_job(path: Path) -> Job:
    """Read and validate one job definition."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    try:
        return _parse(raw, path.stem)
    except JobError as err:
        raise JobError(f"{path}: {err}") from None


def load_jobs(directory: Path) -> dict[str, Job]:
    """Load every `*.toml` in `directory`, keyed by job name."""
    return {job.name: job for job in map(load_job, sorted(directory.glob("*.toml")))}


def _parse(raw: dict[str, Any], stem: str) -> Job:
    if unknown := set(raw) - _FIELDS:
        raise JobError(f"unknown keys {sorted(unknown)}")
    if missing := _REQUIRED - set(raw):
        raise JobError(f"missing keys {sorted(missing)}")

    name = _string(raw, "name")
    if name != stem:
        raise JobError(f"name {name!r} must match the file name {stem!r}")

    inputs = frozenset(_enum(Input, v, "input") for v in _strings(raw, "inputs", []))
    image = _string(raw, "image")
    _check_image(image, inputs)

    command = tuple(_strings(raw, "command"))
    if not command:
        raise JobError("command is empty")
    for arg in command:
        used = {f for _, f, _, _ in string.Formatter().parse(arg) if f is not None}
        if unknown := used - PLACEHOLDERS:
            allowed = sorted(PLACEHOLDERS)
            raise JobError(f"command uses {sorted(unknown)}; allowed: {allowed}")

    out_mount = raw.get("out_mount", DEFAULT_OUT_MOUNT)
    mount = PurePosixPath(out_mount) if isinstance(out_mount, str) else None
    if mount is None or not mount.is_absolute() or str(mount) == "/":
        raise JobError(f"out_mount {out_mount!r} must be an absolute path below /")
    if any(
        mount.is_relative_to(t) or PurePosixPath(t).is_relative_to(mount)
        for t in _TAKEN_MOUNTS
    ):
        raise JobError(f"out_mount {out_mount!r} overlaps one of {list(_TAKEN_MOUNTS)}")

    # A path out of the run directory could make lab reimport a file the job
    # did not write.
    report = _string(raw, "report")
    parts = PurePosixPath(report)
    if parts.is_absolute() or ".." in parts.parts:
        raise JobError(f"report {report!r} must be a relative path inside {out_mount}")

    assets = raw.get("assets")
    if assets is not None and not isinstance(assets, str):
        raise JobError("assets must be a string")

    entrypoint = raw.get("entrypoint")
    if entrypoint is not None and (not isinstance(entrypoint, str) or not entrypoint):
        raise JobError("entrypoint must be a non-empty string")

    scans_image = raw.get("scans_image")
    if scans_image is not None:
        if scans_image not in BUILT_IMAGES:
            raise JobError(
                f"scans_image {scans_image!r} is not one of {sorted(BUILT_IMAGES)}"
            )
        if Input.IMAGES not in inputs:
            raise JobError(f"scans_image needs {Input.IMAGES!s} in inputs")

    secrets = tuple(_strings(raw, "secrets", []))
    for secret in secrets:
        if not _SECRET_NAME.fullmatch(secret):
            raise JobError(f"secret {secret!r} must be lowercase words joined by '-'")
        if secret_env_name(secret) in RESERVED_ENV:
            raise JobError(f"secret {secret!r} would shadow {secret_env_name(secret)}")

    return Job(
        name=name,
        image=image,
        command=command,
        report=report,
        scans_image=scans_image,
        inputs=inputs,
        assets=assets,
        secrets=secrets,
        timeout_seconds=_duration(raw.get("timeout", DEFAULT_TIMEOUT)),
        out_mount=str(mount),
        entrypoint=entrypoint,
    )


def _duration(value: object) -> int:
    """'45m' to 2700. Seconds, minutes or hours, as a whole number."""
    match = _DURATION.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise JobError(f"timeout {value!r} must look like '30s', '45m' or '2h'")
    seconds = int(match[1]) * {"s": 1, "m": 60, "h": 3600}[match[2]]
    if seconds > MAX_TIMEOUT_SECONDS:
        raise JobError(f"timeout {value!r} exceeds {MAX_TIMEOUT_SECONDS // 3600}h")
    return seconds


def _check_image(image: str, inputs: frozenset[Input]) -> None:
    if image.startswith("@"):
        if image[1:] not in BUILT_IMAGES:
            raise JobError(
                f"unknown built image {image!r}; known: {sorted(BUILT_IMAGES)}"
            )
        if Input.IMAGES not in inputs:
            raise JobError(
                f"{image!r} is built from {Input.IMAGES!s}; declare it in inputs"
            )
        return
    # Pinned, so a rebuild cannot change the tool, and its findings, unseen.
    if "@sha256:" in image:
        return
    tag = image.rsplit("/", 1)[-1].partition(":")[2]
    if not tag or tag == "latest":
        raise JobError(f"image {image!r} must pin a version tag or digest")


def _enum[E: StrEnum](cls: type[E], value: str, what: str) -> E:
    try:
        return cls(value)
    except ValueError:
        raise JobError(
            f"unknown {what} {value!r}; known: {[m.value for m in cls]}"
        ) from None


def _string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise JobError(f"{key} must be a non-empty string")
    return value


def _strings(
    raw: dict[str, Any], key: str, default: list[str] | None = None
) -> list[str]:
    value = raw.get(key, default)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise JobError(f"{key} must be a list of strings")
    return value
