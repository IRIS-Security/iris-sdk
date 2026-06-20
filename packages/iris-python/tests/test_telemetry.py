"""Tests for IRIS telemetry opt-out and internal/CI exclusion."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from iris import _telemetry


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IRIS_TELEMETRY_OPT_OUT", raising=False)
    monkeypatch.delenv("IRIS_TELEMETRY_INTERNAL", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def test_telemetry_enabled_by_default() -> None:
    with patch.object(_telemetry, "TELEMETRY_ENABLED", True):
        assert _telemetry.telemetry_enabled() is True


def test_telemetry_opt_out() -> None:
    with patch.dict(os.environ, {"IRIS_TELEMETRY_OPT_OUT": "1"}):
        assert _telemetry.telemetry_enabled() is False


def test_telemetry_skips_ci() -> None:
    with patch.object(_telemetry, "TELEMETRY_ENABLED", True):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            assert _telemetry.telemetry_enabled() is False


def test_telemetry_skips_internal_flag() -> None:
    with patch.object(_telemetry, "TELEMETRY_ENABLED", True):
        with patch.dict(os.environ, {"IRIS_TELEMETRY_INTERNAL": "1"}):
            assert _telemetry.telemetry_enabled() is False


def test_telemetry_skips_iris_sdk_path() -> None:
    with patch.object(_telemetry, "TELEMETRY_ENABLED", True):
        with patch.object(_telemetry.shutil, "which", return_value="/Users/dev/iris-sdk/.venv/bin/iris"):
            assert _telemetry.telemetry_enabled() is False
