"""Job definitions: one TOML file per scanner, validated when loaded."""

from __future__ import annotations

import string
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any


class ScanType(StrEnum):
    """DefectDojo parser names, from `dojo/tools/*/parser.py` at 3.4.101.

    A job's `scan_type` must be one of these. `lab run --check` looks the name
    up in the deployed DefectDojo, so a rename in an upgrade fails there.
    """

    ZAP = "ZAP Scan"
    TRIVY = "Trivy Scan"
    SEMGREP = "Semgrep JSON Report"
    GARAK = "Garak Scan"
    PROMPTFOO = "Promptfoo Scan"
    GENERIC = "Generic Findings Import"
    SARIF = "SARIF"


class Input(StrEnum):
    """What lab builds from Precogly at the run's commit, once per run."""

    SOURCE = "precogly-source"
    IMAGES = "precogly-images"


# Images built from Input.IMAGES, usable as a job's image with "@".
BUILT_IMAGES = frozenset({"precogly-backend", "precogly-frontend"})

# The only placeholders a command may use.
PLACEHOLDERS = frozenset({"target_url", "precogly_sha", "run_id"})

_FIELDS = frozenset(
    {"name", "image", "command", "report", "scan_type", "inputs", "assets"}
)
_REQUIRED = frozenset({"name", "image", "command", "report", "scan_type"})


class JobError(ValueError):
    """A job definition that cannot be run."""


@dataclass(frozen=True)
class Job:
    name: str
    image: str
    command: tuple[str, ...]
    report: str
    scan_type: ScanType
    inputs: frozenset[Input]
    assets: str | None

    @property
    def built_image(self) -> str | None:
        """The built image this job runs in, or None for a registry image."""
        return self.image.removeprefix("@") if self.image.startswith("@") else None


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

    # A path out of /out could make lab reimport a file the job did not write.
    report = _string(raw, "report")
    parts = PurePosixPath(report)
    if parts.is_absolute() or ".." in parts.parts:
        raise JobError(f"report {report!r} must be a path inside /out")

    assets = raw.get("assets")
    if assets is not None and not isinstance(assets, str):
        raise JobError("assets must be a string")

    return Job(
        name=name,
        image=image,
        command=command,
        report=report,
        scan_type=_enum(ScanType, _string(raw, "scan_type"), "scan_type"),
        inputs=inputs,
        assets=assets,
    )


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
