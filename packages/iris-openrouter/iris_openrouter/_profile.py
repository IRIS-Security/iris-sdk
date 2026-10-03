"""Map OpenRouter activity rows to a WorkloadProfile scan payload."""

from __future__ import annotations

from typing import Any

from iris.scan import infer_provider_from_model


def _requests(row: dict[str, Any]) -> int:
    try:
        return int(row.get("requests") or 0)
    except (TypeError, ValueError):
        return 0


def _model(row: dict[str, Any]) -> str | None:
    model = row.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip().lower()
    return None


def _provider(row: dict[str, Any]) -> str | None:
    """Serving provider for a row.

    OpenRouter's `provider_name` is the provider that actually served the
    request (e.g. "OpenAI", "Together") — where the data went — so it wins.
    Fall back to the shared model-name inference only if it is missing.
    """
    name = row.get("provider_name")
    if isinstance(name, str) and name.strip():
        return "-".join(name.strip().lower().split())
    model = _model(row)
    if not model:
        return None
    # OpenRouter slugs are "<author>/<model>"; the shared helper knows bare
    # model names (claude-, gpt-, ...), so try both forms.
    return infer_provider_from_model(model) or infer_provider_from_model(model.split("/", 1)[-1])


def _active_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _requests(row) > 0 and _model(row)]


def summarize_activity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per (model, provider) request and token volume, highest request count first.

    Volume is not part of the WorkloadProfile shape, so it is reported here.
    """
    totals: dict[tuple[str, str | None], dict[str, Any]] = {}
    for row in _active_rows(rows):
        key = (_model(row), _provider(row))
        entry = totals.setdefault(
            key,
            {"model": key[0], "provider": key[1], "requests": 0, "prompt_tokens": 0, "completion_tokens": 0},
        )
        entry["requests"] += _requests(row)
        for field in ("prompt_tokens", "completion_tokens"):
            try:
                entry[field] += int(row.get(field) or 0)
            except (TypeError, ValueError):
                pass
    return sorted(totals.values(), key=lambda item: (-item["requests"], item["model"]))


def build_profile_from_activity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a WorkloadProfileScan-compatible payload from OpenRouter activity rows.

    Activity carries model and provider metadata only — no prompt content,
    tool calls, agent identity, or deployment region. Those signals keep the
    same defaults as the other adapters rather than being guessed.
    """
    active = _active_rows(rows)
    models = sorted({model for row in active if (model := _model(row))})
    providers = sorted({provider for row in active if (provider := _provider(row))})

    return {
        "source": "sdk_scan",
        "models": models,
        "providers": providers,
        "frameworks": ["openrouter"] if models else [],
        "data_categories": [],
        "deployment_regions": ["us"],
        "agent_count": 1 if models else 0,
        "autonomy_level": "assistive",
        "customer_facing": False,
    }
