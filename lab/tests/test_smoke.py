"""The CLI loads every shipped definition and refuses what is not built."""

from __future__ import annotations

from pathlib import Path

import pytest

import lab
from lab import main as main_module
from lab.command.fake import FakeRunner
from lab.main import main


def test_version_is_set() -> None:
    assert lab.__version__


def test_jobs_lists_every_shipped_job(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["jobs"]) == 0
    assert "zap-baseline" in capsys.readouterr().out


def test_run_needs_names_or_all_not_both() -> None:
    assert main(["run", "--dry-run"]) == 1
    assert main(["run", "zap-baseline", "--all", "--dry-run"]) == 1


def test_open_derives_each_url_and_precogly_is_pentest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box = FakeRunner()
    box.on("tailscale", "status", stdout='{"MagicDNSSuffix": "tail1234.ts.net"}')
    monkeypatch.setattr(main_module, "LiveRunner", lambda: box)

    assert main(["open", "precogly", "-n"]) == 0
    assert main(["open", "pentest", "-n"]) == 0
    assert main(["open", "secobserve", "-n"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "https://pentest.tail1234.ts.net",
        "https://pentest.tail1234.ts.net",
        "https://secobserve.tail1234.ts.net",
    ]


def test_run_off_the_scanner_box_says_where_runs_go(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A laptop has no /var/lib/lab; the first mkdir would fail with only
    # "Permission denied".
    monkeypatch.setattr(main_module, "ROOT", tmp_path / "no-such-dir")
    assert main(["run", "zap-baseline"]) == 1
    assert "--remote" in capsys.readouterr().err
