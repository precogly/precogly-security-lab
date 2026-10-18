"""A run, through DryRunRunner: what it reads, and what it would change."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from lab.command import DryRunRunner, Effect
from lab.command.fake import FakeRunner
from lab.command.secobserve import Counts
from lab.job import Input, load_job
from lab.run import Status, execute, run_id
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
    rid, _ = execute([ZAP], TARGET, DryRunRunner(box, out), now=NOW, root=tmp_path)

    assert rid == "20261017T163000Z-94dd831"
    # Everything that reached the box was a read.
    assert all(c.effect is Effect.READ for c in box.commands)
    printed = out.getvalue().splitlines()
    assert printed[0].startswith(f"would run: mkdir -p {tmp_path}/runs/{rid}")
    assert "tee" in printed[1]
    docker_run = next(line for line in printed if "docker run" in line)
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


TOKEN = "so-token-0123456789abcdef"
UPLOAD = "/api/import/file_upload_observations_by_name/"


def real_box() -> FakeRunner:
    box = lab_box()
    box.on("aws", "secretsmanager", stdout=TOKEN + "\n")
    box.respond(
        "POST",
        UPLOAD,
        body=json.dumps(
            {
                "observations_new": 13,
                "observations_updated": 0,
                "observations_resolved": 0,
            }
        ),
    )
    # ZAP exits 2 for warnings; that is not a failure.
    box.on("docker", "run", returncode=2)
    return box


def meta(box: FakeRunner) -> dict[str, object]:
    tee = [c for c in box.commands if c.argv[:1] == ("tee",)][-1]
    assert tee.argv[1].endswith("meta.json")
    assert tee.stdin is not None
    doc = json.loads(tee.stdin)
    assert isinstance(doc, dict)
    return doc


def test_a_finished_job_is_uploaded_and_recorded(tmp_path: Path) -> None:
    box = real_box()
    _, [outcome] = execute([ZAP], TARGET, box, now=NOW, root=tmp_path)

    assert (outcome.status, outcome.exit_code) == (Status.OK, 2)
    assert outcome.observations == Counts(new=13, updated=0, resolved=0)
    [upload] = box.requests
    assert upload.url == f"https://secobserve.tail1234.ts.net{UPLOAD}"
    assert upload.form == {
        "product_name": "Precogly",
        "branch_name": "main",
        "service": "zap-baseline",
    }
    # The token travels only as a secret header.
    assert upload.headers == {"Authorization": f"APIToken {TOKEN}"}
    assert not any(TOKEN in arg for c in box.commands for arg in c.argv)
    assert meta(box)["status"] == "ok"


def test_a_missing_report_is_never_uploaded(tmp_path: Path) -> None:
    # An upload resolves every finding the report lacks, so sending nothing
    # would resolve the job's whole history.
    box = real_box()
    box.on("test", "-s", returncode=1)
    _, [outcome] = execute([ZAP], TARGET, box, now=NOW, root=tmp_path)

    assert outcome.status is Status.FAILED
    assert not box.requests
    assert meta(box)["status"] == "failed"


def test_a_timeout_kills_the_container_and_is_not_reimported(tmp_path: Path) -> None:
    box = real_box()
    box.times_out("docker", "run")
    _, [outcome] = execute([ZAP], TARGET, box, now=NOW, root=tmp_path)

    assert outcome.status is Status.TIMEOUT
    assert (
        "docker",
        "kill",
        "lab-20261017t163000z-94dd831-zap-baseline",
    ) in box.argvs()
    assert not box.requests


def test_one_failed_job_does_not_stop_the_next(tmp_path: Path) -> None:
    box = real_box()
    box.times_out(
        "docker", "run", "--rm", "--name", "lab-20261017t163000z-94dd831-first"
    )
    first, second = replace(ZAP, name="first"), replace(ZAP, name="second")
    _, outcomes = execute([first, second], TARGET, box, now=NOW, root=tmp_path)
    assert [o.status for o in outcomes] == [Status.TIMEOUT, Status.OK]


def test_sarif_is_uploaded_with_repository_paths(tmp_path: Path) -> None:
    # A path that depends on where the source was mounted would change between
    # runs, and every finding would count as new.
    box = real_box()
    report = {
        "runs": [
            {
                "tool": {"driver": {"name": "Semgrep"}},
                "results": [
                    {
                        "ruleId": "r",
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {
                                        "uri": "/in/precogly-source/backend/app.py"
                                    }
                                }
                            }
                        ],
                    }
                ],
            }
        ]
    }
    box.on("cat", stdout=json.dumps(report))
    semgrep = replace(ZAP, name="semgrep", report="report.sarif", out_mount="/out")
    _, [outcome] = execute([semgrep], TARGET, box, now=NOW, root=tmp_path)

    assert outcome.status is Status.OK
    [prepared] = [
        c
        for c in box.commands
        if c.argv[:1] == ("tee",) and c.argv[1].endswith("upload.sarif")
    ]
    assert prepared.stdin is not None
    doc = json.loads(prepared.stdin)
    uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
        "artifactLocation"
    ]["uri"]
    assert uri == "backend/app.py"
    [upload] = box.requests
    assert upload.file is not None
    assert upload.file[1].name == "upload.sarif"


def test_a_run_reports_each_job_as_it_starts_and_ends(tmp_path: Path) -> None:
    # The events a follower draws; the version event is the writer's, not the
    # run's, so it is not here.
    box = real_box()
    events: list[dict[str, object]] = []
    first, second = replace(ZAP, name="first"), replace(ZAP, name="second")
    execute(
        [first, second], TARGET, box, now=NOW, root=tmp_path, on_event=events.append
    )

    kinds = [(e["type"], e.get("job")) for e in events]
    assert kinds == [
        ("run", None),
        ("job_started", "first"),
        ("job_finished", "first"),
        ("job_started", "second"),
        ("job_finished", "second"),
        ("run_finished", None),
    ]
    assert events[0]["jobs"] == ["first", "second"]
    assert events[2]["observations"] == {"new": 13, "updated": 0, "resolved": 0}
    assert events[-1]["ok"] is True


def test_a_stack_is_ready_before_the_job_and_always_removed(tmp_path: Path) -> None:
    box = real_box()
    stack = replace(ZAP, name="schemathesis", inputs=frozenset({Input.STACK}))
    execute([stack], TARGET, box, now=NOW, root=tmp_path)

    commands = box.argvs()
    up = next(
        i for i, argv in enumerate(commands) if argv[-2:] == ("--detach", "--wait")
    )
    scan = next(i for i, argv in enumerate(commands) if argv[:2] == ("docker", "run"))
    down = next(i for i, argv in enumerate(commands) if "down" in argv)
    assert up < scan < down
    assert "--volumes" in commands[down]
    assert "lab-20261017t163000z-94dd831-schemathesis_stack" in commands[scan]
