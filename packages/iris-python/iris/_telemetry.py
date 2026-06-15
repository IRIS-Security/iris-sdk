"""First-run telemetry for IRIS SDK installs. Opt-out via IRIS_TELEMETRY_OPT_OUT=1."""

from __future__ import annotations

import os
import shutil
import sys
import threading
import uuid
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from iris._telemetry_config import TELEMETRY_ENABLED, TELEMETRY_ENDPOINT

_IRIS_DIR = Path.home() / ".iris"
_INSTALL_ID_FILE = _IRIS_DIR / "install_id"
_FIRST_RUN_SENTINEL = _IRIS_DIR / ".telemetry_sent"
_FIRST_POLICY_SENTINEL = _IRIS_DIR / ".first_policy_sent"


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


def telemetry_enabled() -> bool:
    return TELEMETRY_ENABLED and not telemetry_opted_out()


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


def _build_payload(event: str) -> dict[str, str]:
    return {
        "event": event,
        "install_id": _get_or_create_install_id(),
        "install_method": detect_install_method(),
        "python_version": sys.version,
        "platform": sys.platform,
        "iris_version": _get_iris_version(),
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _send_event(event: str) -> None:
    try:
        import httpx

        httpx.post(TELEMETRY_ENDPOINT, json=_build_payload(event), timeout=2.0)
    except Exception:
        pass


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


def send_ping() -> None:
    """Fire a test telemetry ping event (internal verification)."""
    if not telemetry_enabled():
        return
    _send_event("ping")
