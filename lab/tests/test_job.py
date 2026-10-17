"""Job definitions: what loads, and what each rule rejects."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab.job import Input, JobError, ScanType, load_job, load_jobs

ZAP = """
name      = "zap-baseline"
image     = "ghcr.io/zaproxy/zaproxy:2.17.0"
command   = ["zap-baseline.py", "-t", "{target_url}", "-x", "/out/report.xml"]
report    = "report.xml"
scan_type = "ZAP Scan"
"""


def write(tmp_path: Path, body: str, name: str = "zap-baseline") -> Path:
    path = tmp_path / f"{name}.toml"
    path.write_text(body)
    return path


def test_loads_a_registry_job(tmp_path: Path) -> None:
    job = load_job(write(tmp_path, ZAP))
    assert job.scan_type is ScanType.ZAP
    assert job.command[2] == "{target_url}"
    assert job.inputs == frozenset()
    assert job.built_image is None


def test_loads_a_job_running_in_a_built_image(tmp_path: Path) -> None:
    body = """
name      = "harness"
image     = "@precogly-backend"
inputs    = ["precogly-images"]
command   = ["python", "/job/run.py"]
assets    = "harness"
report    = "findings.json"
scan_type = "Generic Findings Import"
"""
    job = load_job(write(tmp_path, body, "harness"))
    assert job.built_image == "precogly-backend"
    assert job.inputs == {Input.IMAGES}


def test_load_jobs_keys_by_name(tmp_path: Path) -> None:
    write(tmp_path, ZAP)
    assert list(load_jobs(tmp_path)) == ["zap-baseline"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("ZAP Scan", "Zap Scan"), "unknown scan_type 'Zap Scan'"),
        (("2.17.0", "latest"), "must pin a version tag or digest"),
        (("zaproxy:2.17.0", "zaproxy"), "must pin a version tag or digest"),
        (("{target_url}", "{target_host}"), "command uses ['target_host']"),
        (('"report.xml"', '"../../etc/passwd"'), "must be a path inside /out"),
        (('"report.xml"', '"/etc/passwd"'), "must be a path inside /out"),
        (('name      = "zap-baseline"', 'name = "zap"'), "must match the file name"),
    ],
)
def test_rejects(tmp_path: Path, change: tuple[str, str], message: str) -> None:
    with pytest.raises(JobError, match=message.replace("[", r"\[").replace("]", r"\]")):
        load_job(write(tmp_path, ZAP.replace(*change)))


def test_rejects_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(JobError, match="unknown keys"):
        load_job(write(tmp_path, ZAP + 'timeout = "1h"\n'))


def test_rejects_a_built_image_without_its_input(tmp_path: Path) -> None:
    body = ZAP.replace("ghcr.io/zaproxy/zaproxy:2.17.0", "@precogly-backend")
    with pytest.raises(JobError, match="declare it in inputs"):
        load_job(write(tmp_path, body))


# A registry host with a port has a colon but no tag; an image under it must
# still be rejected, and a tagged one accepted.
@pytest.mark.parametrize(
    ("image", "ok"),
    [
        ("localhost:5000/scanner", False),
        ("localhost:5000/scanner:1.2", True),
        ("aquasec/trivy@sha256:" + "0" * 64, True),
    ],
)
def test_image_pinning(tmp_path: Path, image: str, ok: bool) -> None:
    path = write(tmp_path, ZAP.replace("ghcr.io/zaproxy/zaproxy:2.17.0", image))
    if ok:
        assert load_job(path).image == image
    else:
        with pytest.raises(JobError):
            load_job(path)
