"""The input cache: only the commit being run is kept."""

from __future__ import annotations

import io
from pathlib import Path

from lab import inputs
from lab.command import DryRunRunner
from lab.command.fake import FakeRunner

SHA = "94dd831e710fe11d7f344d0cddee3003c8819f2f"
OLD = "1111111111111111111111111111111111111111"


def cached(root: Path) -> FakeRunner:
    for sha in (SHA, OLD):
        (root / "inputs" / sha / "precogly-images").mkdir(parents=True)
    box = FakeRunner()
    for name in ("precogly-backend", "precogly-frontend"):
        box.on(
            "docker",
            "image",
            "ls",
            "--format",
            "{{.Repository}}:{{.Tag}}",
            f"lab/{name}",
            stdout=f"lab/{name}:{SHA}\nlab/{name}:{OLD}\n",
        )
    return box


def test_only_other_commits_are_deleted(tmp_path: Path) -> None:
    box = cached(tmp_path)
    inputs.prune(box, SHA, tmp_path)

    assert ("rm", "-rf", "--", str(tmp_path / "inputs" / OLD)) in box.argvs()
    removed = [a for a in box.argvs() if a[:3] == ("docker", "image", "rm")]
    assert removed == [
        ("docker", "image", "rm", f"lab/precogly-backend:{OLD}"),
        ("docker", "image", "rm", f"lab/precogly-frontend:{OLD}"),
    ]
    assert not any(SHA in arg for a in removed for arg in a)
    assert not any(a[:2] == ("rm", "-rf") and SHA in a[-1] for a in box.argvs())


def test_nothing_cached_is_nothing_to_do(tmp_path: Path) -> None:
    box = FakeRunner()
    inputs.prune(box, SHA, tmp_path)
    assert not [a for a in box.argvs() if a[0] == "rm" or a[2] == "rm"]


def test_a_dry_run_prints_the_deletions_and_makes_none(tmp_path: Path) -> None:
    box, out = cached(tmp_path), io.StringIO()
    inputs.prune(DryRunRunner(box, out), SHA, tmp_path)

    # The listings are reads, so they ran; the deletions are writes, so only shown.
    assert all(a[:3] == ("docker", "image", "ls") for a in box.argvs())
    assert f"would run: rm -rf -- {tmp_path / 'inputs' / OLD}" in out.getvalue()
    assert f"lab/precogly-backend:{OLD}" in out.getvalue()
    assert (tmp_path / "inputs" / OLD).is_dir()
