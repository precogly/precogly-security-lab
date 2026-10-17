"""The `docker run` a job gets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lab.container import Run, run_args
from lab.job import Input, Job, ScanType

RUN = Run(
    run_id="20261017T1630Z-94dd831",
    precogly_sha="94dd831e710fe11d7f344d0cddee3003c8819f2f",
    target_url="https://pentest.tail1234.ts.net",
    target_host="pentest.tail1234.ts.net",
    target_ip="100.64.0.7",
    out_dir=Path("/var/lib/lab/runs/20261017T1630Z-94dd831/zap"),
    target_json=Path("/var/lib/lab/runs/20261017T1630Z-94dd831/target.json"),
    inputs={Input.IMAGES: Path("/var/lib/lab/inputs/94dd831/precogly-images")},
    assets_dir=Path("/opt/lab/harness"),
)

ZAP = Job(
    name="zap",
    image="ghcr.io/zaproxy/zaproxy:2.17.0",
    command=("zap-baseline.py", "-t", "{target_url}", "-x", "/out/report.xml"),
    report="report.xml",
    scan_type=ScanType.ZAP,
    inputs=frozenset(),
    assets=None,
    secrets=(),
    timeout_seconds=3600,
    out_mount="/out",
)


def test_fills_placeholders_and_pins_the_target() -> None:
    args = run_args(ZAP, RUN)
    assert args[-5:] == [
        "zap-baseline.py",
        "-t",
        "https://pentest.tail1234.ts.net",
        "-x",
        "/out/report.xml",
    ]
    assert "pentest.tail1234.ts.net:100.64.0.7" in args
    assert "TARGET_URL=https://pentest.tail1234.ts.net" in args
    assert "lab-20261017t1630z-94dd831-zap" in args


def test_never_uses_the_host_network() -> None:
    # Host networking would let a job reach the metadata service and take the
    # scanner box's role, which can read lab's DefectDojo token.
    args = run_args(ZAP, RUN)
    assert args[args.index("--network") + 1] == "bridge"
    assert "host" not in args


def test_secrets_are_passed_by_name_never_by_value() -> None:
    args = run_args(replace(ZAP, secrets=("anthropic-api-key",)), RUN)
    assert args[args.index("ANTHROPIC_API_KEY") - 1] == "--env"
    assert not any(a.startswith("ANTHROPIC_API_KEY=") for a in args)


def test_mounts_only_declared_inputs_read_only() -> None:
    assert not any("/in/" in a for a in run_args(ZAP, RUN))

    harness = replace(
        ZAP,
        name="harness",
        image="@precogly-backend",
        command=("python", "/job/run.py"),
        scan_type=ScanType.GENERIC,
        inputs=frozenset({Input.IMAGES}),
        assets="harness",
    )
    args = run_args(harness, RUN)
    images = "/var/lib/lab/inputs/94dd831/precogly-images"
    assert f"{images}:/in/precogly-images:ro" in args
    assert "/opt/lab/harness:/job:ro" in args
    assert f"lab/precogly-backend:{RUN.precogly_sha}" in args


def test_mounts_the_run_directory_where_the_job_asks() -> None:
    # zap-baseline.py only writes reports under /zap/wrk.
    args = run_args(replace(ZAP, out_mount="/zap/wrk"), RUN)
    assert f"{RUN.out_dir}:/zap/wrk" in args
    assert "OUT_DIR=/zap/wrk" in args
