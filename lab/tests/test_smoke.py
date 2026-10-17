"""Smoke tests for lab."""

from __future__ import annotations

import lab


def test_version_is_set() -> None:
    assert lab.__version__


def test_main_runs() -> None:
    from lab.main import main

    assert main([]) == 0
