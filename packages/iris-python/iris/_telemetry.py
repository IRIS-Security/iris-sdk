"""First-run telemetry for IRIS SDK installs. Opt-out via IRIS_TELEMETRY_OPT_OUT=1.

Each event includes an ISO 8601 UTC timestamp for server-side DoD/WoW/MoM aggregation.
Daily CLI usage is aggregated locally and sent once per UTC day (previous day's totals).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import uuid
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from iris._telemetry_config import TELEMETRY_ENABLED, TELEMETRY_ENDPOINT

_IRIS_DIR = Path.home() / ".iris"
_INSTALL_ID_FILE = _IRIS_DIR / "install_id"
_FIRST_RUN_SENTINEL = _IRIS_DIR / ".telemetry_sent"
_FIRST_POLICY_SENTINEL = _IRIS_DIR / ".first_policy_sent"
_RUN_STATS_FILE = _IRIS_DIR / "run_stats.json"
_SKIPPED_COMMANDS = frozenset({"ping"})


def detect_country() -> str:
    """Infer ISO 3166-1 alpha-2 country from system locale (not GPS or IP)."""
    candidates: list[str] = []
    for env in ("LC_ALL", "LC_CTYPE", "LANG"):
        val = os.environ.get(env, "").strip()
        if val:
            candidates.append(val)

    try:
        import locale

        for getter in (locale.getlocale, locale.getdefaultlocale):
            try:
                loc = getter()
                if loc and loc[0]:
                    candidates.append(loc[0])
            except Exception:
                pass
    except Exception:
        pass

    for tag in candidates:
        normalized = tag.split(".")[0].replace("-", "_")
        parts = normalized.split("_")
        if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
            return parts[-1].upper()
    return "unknown"


def detect_install_method() -> str:
    """Detect how the iris CLI was installed from the executable path."""
    iris_path = shutil.which("iris")
    if not iris_path:
        return "unknown"

    path_lower = iris_path.lower()
    segments = [segment.lower() for segment in Path(iris_path).parts]

    if "pipx" in segments or "pipx" in path_lower:
        return "pipx"
    if "uv" in segments or ".uv" in path_lower:
        return "uv"
    if "site-packages" in segments or "dist-packages" in segments:
        return "pip"
    return "unknown"


def telemetry_opted_out() -> bool:
    return os.environ.get("IRIS_TELEMETRY_OPT_OUT", "").strip() in {"1", "true", "yes"}


def _is_ci_environment() -> bool:
    ci_markers = (
        "CI",
        "CONTINUOUS_INTEGRATION",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "JENKINS_URL",
        "BUILDKITE",
        "CIRCLECI",
        "TRAVIS",
        "TEAMCITY_VERSION",
        "AZURE_HTTP_USER_AGENT",
        "CODEBUILD_BUILD_ID",
    )
    return any(os.environ.get(name) for name in ci_markers)


def _is_internal_install() -> bool:
    if os.environ.get("IRIS_TELEMETRY_INTERNAL", "").strip() in {"1", "true", "yes"}:
        return True

    iris_path = shutil.which("iris") or ""
    path_lower = iris_path.lower()
    internal_markers = ("iris-sdk", "/packages/", "editable")
    return any(marker in path_lower for marker in internal_markers)


def telemetry_enabled() -> bool:
    if not TELEMETRY_ENABLED or telemetry_opted_out():
        return False
    if _is_ci_environment() or _is_internal_install():
        return False
    return True


def _get_or_create_install_id() -> str:
    _IRIS_DIR.mkdir(parents=True, exist_ok=True)
    if _INSTALL_ID_FILE.exists():
        install_id = _INSTALL_ID_FILE.read_text(encoding="utf-8").strip()
        if install_id:
            return install_id

    install_id = str(uuid.uuid4())
    _INSTALL_ID_FILE.write_text(install_id, encoding="utf-8")
    return install_id


def _get_iris_version() -> str:
    try:
        return version("iris-security-sdk")
    except PackageNotFoundError:
        return "unknown"


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _build_payload(event: str) -> dict[str, str]:
    return {
        "event": event,
        "install_id": _get_or_create_install_id(),
        "install_method": detect_install_method(),
        "country": detect_country(),
        "python_version": sys.version,
        "platform": sys.platform,
        "iris_version": _get_iris_version(),
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "ci": "true" if _is_ci_environment() else "false",
        "internal": "true" if _is_internal_install() else "false",
    }


def _build_daily_payload(stats: dict[str, Any]) -> dict[str, str]:
    payload = _build_payload("daily_usage")
    payload["usage_date"] = str(stats["date"])
    payload["run_count"] = str(stats["run_count"])
    payload["commands"] = json.dumps(stats.get("commands", {}), sort_keys=True)
    return payload


def _empty_day_stats(day: str) -> dict[str, Any]:
    return {"date": day, "run_count": 0, "commands": {}}


def _load_run_stats() -> dict[str, Any]:
    if not _RUN_STATS_FILE.exists():
        return _empty_day_stats(_utc_today())
    try:
        data = json.loads(_RUN_STATS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_day_stats(_utc_today())
        data.setdefault("commands", {})
        return data
    except (OSError, json.JSONDecodeError):
        return _empty_day_stats(_utc_today())


def _save_run_stats(stats: dict[str, Any]) -> None:
    _RUN_STATS_FILE.write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")


def _send_payload(payload: dict[str, str]) -> None:
    try:
        import httpx

        httpx.post(TELEMETRY_ENDPOINT, json=payload, timeout=2.0)
    except Exception:
        pass


def _send_event(event: str) -> None:
    _send_payload(_build_payload(event))


def _flush_daily_usage(stats: dict[str, Any]) -> None:
    if int(stats.get("run_count", 0)) <= 0:
        return
    payload = _build_daily_payload(stats)
    thread = threading.Thread(target=_send_payload, args=(payload,), daemon=True)
    thread.start()


def _maybe_fire_once(event: str, sentinel: Path) -> None:
    if not telemetry_enabled():
        return

    if sentinel.exists():
        return

    try:
        _IRIS_DIR.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
    except OSError:
        return

    thread = threading.Thread(target=_send_event, args=(event,), daemon=True)
    thread.start()


def maybe_fire_first_run() -> None:
    """Fire a one-time first-run telemetry event on this machine."""
    _maybe_fire_once("first_run", _FIRST_RUN_SENTINEL)


def maybe_fire_first_policy_run() -> None:
    """Fire a one-time telemetry event after the first policy evaluation."""
    _maybe_fire_once("first_policy_run", _FIRST_POLICY_SENTINEL)


def maybe_record_cli_usage(command: str) -> None:
    """Increment local run counters; send one daily_usage event per UTC day on rollover."""
    if not telemetry_enabled() or not command or command in _SKIPPED_COMMANDS:
        return

    today = _utc_today()
    try:
        _IRIS_DIR.mkdir(parents=True, exist_ok=True)
        stats = _load_run_stats()
    except OSError:
        return

    stored_date = stats.get("date")
    if stored_date != today:
        if stored_date and int(stats.get("run_count", 0)) > 0:
            _flush_daily_usage(stats)
        stats = _empty_day_stats(today)

    commands = stats.setdefault("commands", {})
    commands[command] = int(commands.get(command, 0)) + 1
    stats["run_count"] = int(stats.get("run_count", 0)) + 1

    try:
        _save_run_stats(stats)
    except OSError:
        pass


def send_ping() -> None:
    """Fire a test telemetry ping event (internal verification)."""
    if not telemetry_enabled():
        return
    _send_event("ping")
