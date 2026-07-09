"""Tests for IRIS telemetry opt-out, internal/CI exclusion, and daily usage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from iris import _telemetry


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IRIS_TELEMETRY_OPT_OUT", raising=False)
    monkeypatch.delenv("IRIS_TELEMETRY_INTERNAL", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


@pytest.fixture
def iris_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    iris_dir = tmp_path / ".iris"
    iris_dir.mkdir()
    monkeypatch.setattr(_telemetry, "_IRIS_DIR", iris_dir)
    monkeypatch.setattr(_telemetry, "_INSTALL_ID_FILE", iris_dir / "install_id")
    monkeypatch.setattr(_telemetry, "_FIRST_RUN_SENTINEL", iris_dir / ".telemetry_sent")
    monkeypatch.setattr(_telemetry, "_FIRST_POLICY_SENTINEL", iris_dir / ".first_policy_sent")
    monkeypatch.setattr(_telemetry, "_RUN_STATS_FILE", iris_dir / "run_stats.json")
    return iris_dir


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


def test_maybe_record_cli_usage_increments_local_stats(iris_home: Path) -> None:
    with patch.object(_telemetry, "TELEMETRY_ENABLED", True):
        _telemetry.maybe_record_cli_usage("scan")
        _telemetry.maybe_record_cli_usage("scan")
        _telemetry.maybe_record_cli_usage("compile")

    stats = json.loads((iris_home / "run_stats.json").read_text())
    assert stats["run_count"] == 3
    assert stats["commands"] == {"scan": 2, "compile": 1}


def test_maybe_record_cli_usage_skips_ping(iris_home: Path) -> None:
    with patch.object(_telemetry, "TELEMETRY_ENABLED", True):
        _telemetry.maybe_record_cli_usage("ping")
    assert not (iris_home / "run_stats.json").exists()


def test_day_rollover_flushes_previous_day(iris_home: Path) -> None:
    sent: list[dict[str, str]] = []

    def capture(payload: dict[str, str]) -> None:
        sent.append(payload)

    (iris_home / "run_stats.json").write_text(
        json.dumps({"date": "2026-06-14", "run_count": 5, "commands": {"scan": 5}}),
        encoding="utf-8",
    )

    with patch.object(_telemetry, "TELEMETRY_ENABLED", True):
        with patch.object(_telemetry, "_utc_today", return_value="2026-06-15"):
            with patch.object(_telemetry, "_send_payload", side_effect=capture):
                _telemetry.maybe_record_cli_usage("scan")

    assert len(sent) == 1
    assert sent[0]["event"] == "daily_usage"
    assert sent[0]["usage_date"] == "2026-06-14"
    assert sent[0]["run_count"] == "5"
    assert json.loads(sent[0]["commands"]) == {"scan": 5}

    stats = json.loads((iris_home / "run_stats.json").read_text())
    assert stats["date"] == "2026-06-15"
    assert stats["run_count"] == 1
    assert stats["commands"] == {"scan": 1}
