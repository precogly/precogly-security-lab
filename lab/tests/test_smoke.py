"""The CLI loads every shipped definition and refuses what is not built."""

from __future__ import annotations

import pytest

import lab
from lab.main import main


def test_version_is_set() -> None:
    assert lab.__version__


def test_jobs_lists_every_shipped_job(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["jobs"]) == 0
    assert "zap-baseline" in capsys.readouterr().out


def test_run_needs_names_or_all_not_both() -> None:
    assert main(["run", "--dry-run"]) == 1
    assert main(["run", "zap-baseline", "--all", "--dry-run"]) == 1
