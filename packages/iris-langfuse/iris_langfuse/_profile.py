"""Map Langfuse trace/observation metadata to WorkloadProfile scan payload."""

from __future__ import annotations

from typing import Any

from iris.scan import infer_providers_from_models, scan_data_categories_from_text

_FRAMEWORK_TAG_HINTS = {
    "langchain": "langchain",
    "crewai": "crewai",
    "llama_index": "llama_index",
    "llamaindex": "llama_index",
    "semantic_kernel": "semantic_kernel",
    "autogen": "autogen",
    "haystack": "haystack",
    "litellm": "litellm",
}

_TOOL_OBSERVATION_TYPES = frozenset(
    {"TOOL", "TOOL_CALL", "tool", "tool_call", "SPAN", "AGENT"}
)


def _collect_metadata_text(trace: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("name", "tags"):
        value = trace.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    metadata = trace.get("metadata")
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            parts.append(str(key))
            if isinstance(value, (str, int, float, bool)):
                parts.append(str(value))
    return " ".join(parts)


def _infer_frameworks(traces: list[dict[str, Any]]) -> list[str]:
    frameworks: set[str] = set()
    for trace in traces:
        text = _collect_metadata_text(trace).lower()
        for needle, framework in _FRAMEWORK_TAG_HINTS.items():
            if needle in text:
                frameworks.add(framework)
        metadata = trace.get("metadata")
        if isinstance(metadata, dict):
            for key in ("framework", "integration", "sdk"):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    lowered = value.lower()
                    for needle, framework in _FRAMEWORK_TAG_HINTS.items():
                        if needle in lowered:
                            frameworks.add(framework)
    return sorted(frameworks)


def _infer_data_categories(traces: list[dict[str, Any]]) -> list[str]:
    categories: set[str] = set()
    for trace in traces:
        categories.update(scan_data_categories_from_text(_collect_metadata_text(trace)))
    return sorted(categories)


def _infer_autonomy(observations: list[dict[str, Any]]) -> str:
    tool_calls = 0
    for obs in observations:
        obs_type = str(obs.get("type", "")).upper()
        name = str(obs.get("name", "")).lower()
        if obs_type in _TOOL_OBSERVATION_TYPES or "tool" in name:
            tool_calls += 1
    if tool_calls >= 10:
        return "autonomous"
    if tool_calls >= 1:
        return "supervised"
    return "assistive"


def build_profile_from_langfuse_data(
    traces: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a WorkloadProfileScan-compatible payload from Langfuse metadata."""
    models: set[str] = set()
    for obs in observations:
        model = obs.get("model") or obs.get("modelName")
        if isinstance(model, str) and model.strip():
            models.add(model.strip().lower())
    for trace in traces:
        metadata = trace.get("metadata")
        if isinstance(metadata, dict):
            model = metadata.get("model")
            if isinstance(model, str) and model.strip():
                models.add(model.strip().lower())

    model_list = sorted(models)
    providers = infer_providers_from_models(model_list)
    trace_count = len(traces)
    agent_count = max(trace_count // 5, 1 if model_list else 0)

    return {
        "source": "sdk_scan",
        "models": model_list,
        "providers": providers,
        "frameworks": _infer_frameworks(traces),
        "data_categories": _infer_data_categories(traces),
        "deployment_regions": ["us"],
        "agent_count": agent_count,
        "autonomy_level": _infer_autonomy(observations),
        "customer_facing": any(
            "production" in _collect_metadata_text(trace).lower()
            or "customer" in _collect_metadata_text(trace).lower()
            for trace in traces
        ),
    }
