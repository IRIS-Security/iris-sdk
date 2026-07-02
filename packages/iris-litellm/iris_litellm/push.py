"""Optional push of workload profile to IRIS Cloud /intelligence/profile/scan."""

from __future__ import annotations

import os
from typing import Any

import httpx


def push_profile(profile: dict[str, Any], *, base_url: str | None = None, api_key: str | None = None) -> str:
    """POST profile to IRIS Cloud. Returns a human-readable status message."""
    resolved_key = api_key or os.environ.get("IRIS_API_KEY") or os.environ.get("IRIS_CLOUD_API_KEY")
    resolved_url = (base_url or os.environ.get("IRIS_API_URL") or "http://localhost:8000").rstrip("/")
    if not resolved_key:
        return "Set IRIS_API_KEY to push profile to IRIS Cloud."

    response = httpx.post(
        f"{resolved_url}/intelligence/profile/scan",
        headers={"Authorization": f"Bearer {resolved_key}", "Content-Type": "application/json"},
        json=profile,
        timeout=30,
    )
    if response.status_code >= 400:
        return f"Push failed ({response.status_code}): {response.text}"
    return "Profile pushed to IRIS Cloud."
