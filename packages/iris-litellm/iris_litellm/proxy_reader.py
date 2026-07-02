"""Query LiteLLM proxy /model/info and spend endpoints."""

from __future__ import annotations

import os
from typing import Any

import httpx

from iris.scan import infer_providers_from_models

from iris_litellm._profile import build_profile_from_proxy_info


class IrisLiteLLM:
    """LiteLLM proxy reader for IRIS workload profiles."""

    def __init__(self, *, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("LITELLM_API_KEY")

    def profile(self) -> dict[str, Any]:
        return profile_from_litellm_proxy(self.base_url, api_key=self.api_key)


def _auth_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def fetch_model_info(
    base_url: str,
    *,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/model/info"
    owns_client = client is None
    http = client or httpx.Client(timeout=30)
    try:
        response = http.get(url, headers=_auth_headers(api_key))
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            http.close()

    if isinstance(payload, dict):
        data = payload.get("data") or payload.get("models") or payload.get("model_info")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def fetch_spend_models(
    base_url: str,
    *,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    """Best-effort spend endpoint lookup for models actually invoked."""
    url = f"{base_url.rstrip('/')}/spend/logs"
    owns_client = client is None
    http = client or httpx.Client(timeout=30)
    try:
        response = http.get(url, headers=_auth_headers(api_key))
        if response.status_code >= 400:
            return []
        payload = response.json()
    finally:
        if owns_client:
            http.close()

    models: set[str] = set()
    entries = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                model = entry.get("model") or entry.get("model_name")
                if isinstance(model, str) and model.strip():
                    models.add(model.strip())
    return sorted(models)


def profile_from_litellm_proxy(
    base_url: str,
    *,
    api_key: str | None = None,
    model_info: list[dict[str, Any]] | None = None,
    spend_models: list[str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Derive a WorkloadProfile scan payload from a live LiteLLM proxy."""
    resolved_key = api_key or os.environ.get("LITELLM_API_KEY")
    info = model_info if model_info is not None else fetch_model_info(base_url, api_key=resolved_key, client=client)
    profile = build_profile_from_proxy_info(info)
    if spend_models is None:
        spend_models = fetch_spend_models(base_url, api_key=resolved_key, client=client)
    if spend_models:
        merged_models = sorted(set(profile.get("models", [])) | set(m.lower() for m in spend_models))
        profile["models"] = merged_models
        profile["providers"] = infer_providers_from_models(merged_models)
    return profile
