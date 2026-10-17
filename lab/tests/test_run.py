"""A run, through DryRunRunner: what it reads, and what it would change."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from lab.command import DryRunRunner, Effect
from lab.command.fake import FakeRunner
from lab.job import Input, load_job
from lab.run import execute, run_id
from lab.target import load_target

SHA = "94dd831e710fe11d7f344d0cddee3003c8819f2f"
NOW = datetime(2026, 10, 17, 16, 30, tzinfo=UTC)
ZAP = load_job(Path(str(files("lab") / "jobs" / "zap-baseline.toml")))
TARGET = load_target(Path(str(files("lab") / "targets" / "pentest.toml")))


def lab_box() -> FakeRunner:
    box = FakeRunner()
    box.on("tailscale", "status", stdout='{"MagicDNSSuffix": "tail1234.ts.net"}')
    box.on("tailscale", "ip", stdout="100.64.0.7\n")
    box.on("aws", "ssm", stdout=SHA + "\n")
    # No built images yet.
    box.on("docker", "image", "inspect", returncode=1)
    return box


def test_run_id_sorts_by_time_and_names_the_commit() -> None:
    assert run_id(NOW, SHA) == "20261017T163000Z-94dd831"


def test_dry_run_reads_for_real_and_changes_nothing(tmp_path: Path) -> None:
    box, out = lab_box(), io.StringIO()
    rid = execute([ZAP], TARGET, DryRunRunner(box, out), now=NOW, root=tmp_path)

    assert rid == "20261017T163000Z-94dd831"
    # Everything that reached the box was a read.
    assert all(c.effect is Effect.READ for c in box.commands)
    printed = out.getvalue().splitlines()
    assert printed[0].startswith(f"would run: mkdir -p {tmp_path}/runs/{rid}")
    assert "tee" in printed[1]
    docker_run = printed[-1]
    assert "docker run" in docker_run
    assert "pentest.tail1234.ts.net:100.64.0.7" in docker_run
    assert f"{tmp_path}/runs/{rid}/zap-baseline:/zap/wrk" in docker_run
    assert "https://pentest.tail1234.ts.net" in docker_run


def test_a_job_with_inputs_builds_them_once_for_the_commit(tmp_path: Path) -> None:
    box, out = lab_box(), io.StringIO()
    trivy = replace(
        ZAP, name="trivy-images", inputs=frozenset({Input.IMAGES}), out_mount="/out"
    )
    execute(
        [trivy, replace(trivy, name="trivy-again")],
        TARGET,
        DryRunRunner(box, out),
        now=NOW,
        root=tmp_path,
    )

    printed = out.getvalue()
    # One checkout at exactly the commit, and each image built once although
    # two jobs want them.
    assert printed.count(f"fetch --quiet --depth 1 origin {SHA}") == 1
    assert printed.count(f"--tag lab/precogly-backend:{SHA}") == 1
    assert printed.count(f"--tag lab/precogly-frontend:{SHA}") == 1
    assert printed.count("docker save") == 2
