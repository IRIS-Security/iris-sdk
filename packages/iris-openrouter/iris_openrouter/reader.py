"""Read OpenRouter usage activity and derive workload profile metadata.

This adapter makes a LIVE network call to openrouter.ai — it is not an
offline check. It calls GET https://openrouter.ai/api/v1/activity, which
returns activity grouped by endpoint for the last 30 completed UTC days and
requires an OpenRouter Management API key. Management keys are distinct
from the inference keys used for chat completions:
https://openrouter.ai/docs/guides/overview/auth/management-api-keys
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

from iris_openrouter._profile import build_profile_from_activity

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
MANAGEMENT_KEY_ENV_VAR = "OPENROUTER_MANAGEMENT_KEY"
MANAGEMENT_KEYS_URL = "https://openrouter.ai/settings/management-keys"

WRONG_KEY_TYPE_MESSAGE = (
    "This looks like it might be a regular OpenRouter inference key. "
    "iris-openrouter needs a Management API key to read usage activity, "
    "these are different from the keys used for chat completions. "
    f"Create one at: {MANAGEMENT_KEYS_URL}"
)

# OpenRouter documents no prefix or length that distinguishes a Management key
# from an inference key, so there is no format check for key *type*. The only
# pre-request check is that the key is a syntactically valid bearer token
# (RFC 6750 b64token) — anything else (embedded whitespace, quotes, a pasted
# "Bearer " prefix) can never authenticate, so it is rejected before any
# network call. Key type is decided by OpenRouter's 401/403 response.
_BEARER_TOKEN = re.compile(r"[A-Za-z0-9\-._~+/]+=*")

# Activity fields IRIS reads. Cost fields (usage, byok_usage_inference) and
# anything OpenRouter adds later are dropped.
_SAFE_ACTIVITY_FIELDS = frozenset(
    {
        "date",
        "model",
        "model_permaslug",
        "endpoint_id",
        "provider_name",
        "requests",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "cached_tokens",
    }
)


class ManagementKeyError(ValueError):
    """Missing, malformed, or rejected OpenRouter Management API key."""


class OpenRouterActivityError(RuntimeError):
    """OpenRouter activity request failed for a reason other than the key."""


def _resolve_management_key(api_key: str | None) -> str:
    key = api_key if api_key is not None else os.environ.get(MANAGEMENT_KEY_ENV_VAR)
    key = (key or "").strip()
    if not key:
        raise ManagementKeyError(
            "No OpenRouter Management API key provided. Set "
            f"{MANAGEMENT_KEY_ENV_VAR} or pass api_key=... "
            f"Create one at: {MANAGEMENT_KEYS_URL}"
        )
    if not _BEARER_TOKEN.fullmatch(key):
        raise ManagementKeyError(
            "The provided key is not a well-formed API key (it contains whitespace "
            "or characters an API key cannot contain).\n" + WRONG_KEY_TYPE_MESSAGE
        )
    return key


def _make_client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout)


def _safe_row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in raw if key in _SAFE_ACTIVITY_FIELDS}


def parse_activity_response(payload: Any) -> list[dict[str, Any]]:
    """Normalize a GET /api/v1/activity response body to allowlisted rows."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise OpenRouterActivityError(
            "Unrecognized OpenRouter activity response: expected {'data': [...]}"
        )
    return [row for row in (_safe_row(item) for item in payload["data"]) if row]


def fetch_activity(
    api_key: str | None = None,
    *,
    base_url: str = OPENROUTER_API_BASE,
    timeout: float = 30,
) -> list[dict[str, Any]]:
    """Fetch the last 30 completed UTC days of activity from OpenRouter (live call).

    The key is read from `api_key`, else the OPENROUTER_MANAGEMENT_KEY env var.
    """
    key = _resolve_management_key(api_key)
    try:
        with _make_client(timeout) as client:
            response = client.get(
                f"{base_url.rstrip('/')}/activity",
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.HTTPError as exc:
        raise OpenRouterActivityError(
            f"Could not reach OpenRouter at {base_url} ({type(exc).__name__}). "
            "iris-openrouter needs a live connection to openrouter.ai."
        ) from None

    if response.status_code == 401:
        raise ManagementKeyError(
            WRONG_KEY_TYPE_MESSAGE
            + "\n(If this is a Management key, check that it has not expired or been deleted.)"
        )
    if response.status_code == 403:
        raise ManagementKeyError(WRONG_KEY_TYPE_MESSAGE)
    if response.status_code >= 400:
        raise OpenRouterActivityError(
            f"OpenRouter activity request failed (HTTP {response.status_code})."
        )

    try:
        payload = response.json()
    except ValueError:
        raise OpenRouterActivityError("OpenRouter activity response was not valid JSON.") from None
    return parse_activity_response(payload)


def profile_from_openrouter(
    api_key: str | None = None,
    *,
    base_url: str = OPENROUTER_API_BASE,
    timeout: float = 30,
) -> dict[str, Any]:
    """Derive a WorkloadProfile scan payload from live OpenRouter activity."""
    return build_profile_from_activity(
        fetch_activity(api_key, base_url=base_url, timeout=timeout)
    )
