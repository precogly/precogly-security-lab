"""Job definitions: what loads, and what each rule rejects."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab.job import Input, JobError, load_job, load_jobs

ZAP = """
name      = "zap-baseline"
image     = "ghcr.io/zaproxy/zaproxy:2.17.0"
command   = ["zap-baseline.py", "-t", "{target_url}", "-x", "/out/report.xml"]
report    = "report.xml"
"""


def write(tmp_path: Path, body: str, name: str = "zap-baseline") -> Path:
    path = tmp_path / f"{name}.toml"
    path.write_text(body)
    return path


def test_loads_a_registry_job(tmp_path: Path) -> None:
    job = load_job(write(tmp_path, ZAP))
    assert job.scans_image is None
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
report    = "findings.sarif"
"""
    job = load_job(write(tmp_path, body, "harness"))
    assert job.built_image == "precogly-backend"
    assert job.inputs == {Input.IMAGES}


def test_loads_an_entrypoint_override(tmp_path: Path) -> None:
    job = load_job(write(tmp_path, ZAP + 'entrypoint = "python"\n'))
    assert job.entrypoint == "python"


def test_load_jobs_keys_by_name(tmp_path: Path) -> None:
    write(tmp_path, ZAP)
    assert list(load_jobs(tmp_path)) == ["zap-baseline"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("2.17.0", "latest"), "must pin a version tag or digest"),
        (("zaproxy:2.17.0", "zaproxy"), "must pin a version tag or digest"),
        (("{target_url}", "{target_host}"), "command uses ['target_host']"),
        (('"report.xml"', '"../../etc/passwd"'), "must be a relative path inside /out"),
        (('"report.xml"', '"/etc/passwd"'), "must be a relative path inside /out"),
        (('name      = "zap-baseline"', 'name = "zap"'), "must match the file name"),
    ],
)
def test_rejects(tmp_path: Path, change: tuple[str, str], message: str) -> None:
    with pytest.raises(JobError, match=message.replace("[", r"\[").replace("]", r"\]")):
        load_job(write(tmp_path, ZAP.replace(*change)))


def test_rejects_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(JobError, match="unknown keys"):
        load_job(write(tmp_path, ZAP + "retries = 3\n"))


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


def test_timeout_defaults_and_parses(tmp_path: Path) -> None:
    assert load_job(write(tmp_path, ZAP)).timeout_seconds == 3600
    job = load_job(write(tmp_path, ZAP + 'timeout = "45m"\n'))
    assert job.timeout_seconds == 45 * 60


@pytest.mark.parametrize("timeout", ["45", "1d", "0m", "13h", "-5m"])
def test_rejects_bad_timeouts(tmp_path: Path, timeout: str) -> None:
    with pytest.raises(JobError, match="timeout"):
        load_job(write(tmp_path, ZAP + f'timeout = "{timeout}"\n'))


def test_secrets_map_to_environment_names(tmp_path: Path) -> None:
    job = load_job(write(tmp_path, ZAP + 'secrets = ["anthropic-api-key"]\n'))
    assert job.secret_env == {"anthropic-api-key": "ANTHROPIC_API_KEY"}


@pytest.mark.parametrize(
    ("secret", "message"),
    [
        ("Anthropic_Key", "lowercase words"),
        ("../admin", "lowercase words"),
        # Would replace the TARGET_URL every job relies on.
        ("target-url", "would shadow TARGET_URL"),
    ],
)
def test_rejects_bad_secret_names(tmp_path: Path, secret: str, message: str) -> None:
    with pytest.raises(JobError, match=message):
        load_job(write(tmp_path, ZAP + f'secrets = ["{secret}"]\n'))


@pytest.mark.parametrize(
    ("mount", "ok"),
    [
        ("/zap/wrk", True),
        ("/", False),
        ("zap/wrk", False),
        ("/in", False),
        ("/run", False),
    ],
)
def test_out_mount(tmp_path: Path, mount: str, ok: bool) -> None:
    path = write(tmp_path, ZAP + f'out_mount = "{mount}"\n')
    if ok:
        assert load_job(path).out_mount == mount
    else:
        with pytest.raises(JobError, match="out_mount"):
            load_job(path)


def test_scans_image_names_a_built_image_and_needs_its_input(tmp_path: Path) -> None:
    trivy = """
name        = "trivy-backend"
image       = "aquasec/trivy:0.76.0"
inputs      = ["precogly-images"]
scans_image = "precogly-backend"
command     = ["image", "--input", "/in/precogly-images/backend.tar"]
report      = "report.cdx.json"
"""
    assert load_job(write(tmp_path, trivy, "trivy-backend")).scans_image == (
        "precogly-backend"
    )
    with pytest.raises(JobError, match="scans_image needs"):
        load_job(
            write(
                tmp_path,
                trivy.replace('inputs      = ["precogly-images"]\n', ""),
                "trivy-backend",
            )
        )
    with pytest.raises(JobError, match="is not one of"):
        load_job(
            write(
                tmp_path,
                trivy.replace('"precogly-backend"', '"nginx"'),
                "trivy-backend",
            )
        )


def test_a_parser_name_is_an_unknown_key(tmp_path: Path) -> None:
    # SecObserve detects the parser from the report, so naming one is a mistake.
    with pytest.raises(JobError, match="unknown keys"):
        load_job(write(tmp_path, ZAP + 'scan_type = "ZAP Scan"\n'))
