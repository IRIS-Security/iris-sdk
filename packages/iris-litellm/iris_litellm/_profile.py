"""Map LiteLLM config/proxy data to WorkloadProfile scan payload."""

from __future__ import annotations

from typing import Any

from iris.scan import infer_provider_from_model, infer_providers_from_models


def _provider_from_litellm_entry(entry: dict[str, Any]) -> str | None:
    litellm_params = entry.get("litellm_params") or {}
    if not isinstance(litellm_params, dict):
        litellm_params = {}
    model = litellm_params.get("model") or entry.get("model_name") or entry.get("model")
    if isinstance(model, str):
        inferred = infer_provider_from_model(model)
        if inferred:
            return inferred
        if "/" in model:
            prefix = model.split("/", 1)[0].lower()
            alias = {"gemini": "google", "vertex_ai": "google", "bedrock": "aws"}.get(prefix, prefix)
            return alias
    provider = litellm_params.get("custom_llm_provider") or entry.get("provider")
    if isinstance(provider, str) and provider.strip():
        return provider.strip().lower()
    return None


def build_profile_from_models(
    models: list[str],
    *,
    providers: list[str] | None = None,
    frameworks: list[str] | None = None,
    agent_count: int | None = None,
) -> dict[str, Any]:
    """Build a WorkloadProfileScan-compatible payload from model identifiers."""
    normalized_models = sorted({model.strip().lower() for model in models if model and model.strip()})
    inferred_providers = providers or infer_providers_from_models(normalized_models)
    resolved_frameworks = frameworks or (["litellm"] if normalized_models else [])
    resolved_agent_count = agent_count if agent_count is not None else max(len(normalized_models), 0)

    return {
        "source": "sdk_scan",
        "models": normalized_models,
        "providers": sorted(set(inferred_providers)),
        "frameworks": sorted(set(resolved_frameworks)),
        "data_categories": [],
        "deployment_regions": ["us"],
        "agent_count": resolved_agent_count,
        "autonomy_level": "supervised" if len(normalized_models) >= 3 else "assistive",
        "customer_facing": False,
    }


def build_profile_from_config_entries(model_list: list[dict[str, Any]]) -> dict[str, Any]:
    models: list[str] = []
    providers: set[str] = set()
    for entry in model_list:
        litellm_params = entry.get("litellm_params") or {}
        if not isinstance(litellm_params, dict):
            litellm_params = {}
        model = litellm_params.get("model") or entry.get("model_name")
        if isinstance(model, str) and model.strip():
            models.append(model.strip())
        provider = _provider_from_litellm_entry(entry)
        if provider:
            providers.add(provider)
    profile = build_profile_from_models(models, providers=sorted(providers), frameworks=["litellm"])
    profile["agent_count"] = max(len(model_list), 1 if models else 0)
    return profile


def build_profile_from_proxy_info(model_info: list[dict[str, Any]]) -> dict[str, Any]:
    models: list[str] = []
    providers: set[str] = set()
    for entry in model_info:
        model = entry.get("model_name") or entry.get("id") or entry.get("model")
        if isinstance(model, str) and model.strip():
            models.append(model.strip())
        provider = _provider_from_litellm_entry(entry)
        if provider:
            providers.add(provider)
        litellm_provider = entry.get("litellm_provider")
        if isinstance(litellm_provider, str) and litellm_provider.strip():
            providers.add(litellm_provider.strip().lower())
    return build_profile_from_models(
        models,
        providers=sorted(providers),
        frameworks=["litellm"],
        agent_count=max(len(model_info), 1 if models else 0),
    )
