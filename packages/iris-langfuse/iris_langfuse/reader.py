"""Read Langfuse traces/observations and derive workload profile metadata."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from iris_langfuse._profile import build_profile_from_langfuse_data

# Fields that must never be read — privacy guarantee for prompt/output content.
_FORBIDDEN_CONTENT_FIELDS = frozenset(
    {
        "input",
        "output",
        "prompt",
        "completion",
        "messages",
        "content",
        "promptTokens",
        "completionTokens",
    }
)

_SAFE_TRACE_FIELDS = frozenset(
    {"id", "name", "tags", "metadata", "timestamp", "userId", "sessionId"}
)
_SAFE_OBSERVATION_FIELDS = frozenset(
    {"id", "traceId", "name", "type", "model", "modelName", "metadata", "startTime"}
)


def _safe_dict(raw: Any, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in raw if key in allowed and key not in _FORBIDDEN_CONTENT_FIELDS}


def _normalize_trace(raw: Any) -> dict[str, Any]:
    return _safe_dict(raw, _SAFE_TRACE_FIELDS)


def _normalize_observation(raw: Any) -> dict[str, Any]:
    return _safe_dict(raw, _SAFE_OBSERVATION_FIELDS)


def _require_langfuse() -> Any:
    try:
        from langfuse import Langfuse
    except ImportError as exc:
        raise ImportError(
            'Langfuse SDK not installed. Run: pip install "iris-langfuse[live]"'
        ) from exc
    return Langfuse


class IrisLangfuse:
    """Langfuse reader that derives IRIS workload profiles without reading prompts."""

    def __init__(
        self,
        *,
        host: str | None = None,
        public_key: str | None = None,
        secret_key: str | None = None,
        lookback_days: int = 30,
    ) -> None:
        self.host = host or os.environ.get("LANGFUSE_HOST")
        self.public_key = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY")
        self.secret_key = secret_key or os.environ.get("LANGFUSE_SECRET_KEY")
        self.lookback_days = lookback_days

    def profile(self) -> dict[str, Any]:
        return profile_from_langfuse(
            host=self.host,
            public_key=self.public_key,
            secret_key=self.secret_key,
            lookback_days=self.lookback_days,
        )


def _default_fetch_traces(
    client: Any,
    *,
    from_timestamp: datetime,
    to_timestamp: datetime,
) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    page = 1
    while True:
        response = client.fetch_traces(
            page=page,
            limit=100,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        data = getattr(response, "data", None) or []
        if not data:
            break
        for item in data:
            if hasattr(item, "dict"):
                traces.append(_normalize_trace(item.dict()))
            elif hasattr(item, "model_dump"):
                traces.append(_normalize_trace(item.model_dump()))
            else:
                traces.append(_normalize_trace(item))
        meta = getattr(response, "meta", None)
        total_pages = getattr(meta, "total_pages", page) if meta else page
        if page >= total_pages:
            break
        page += 1
    return traces


def _default_fetch_observations(
    client: Any,
    *,
    from_timestamp: datetime,
    to_timestamp: datetime,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    page = 1
    while True:
        response = client.fetch_observations(
            page=page,
            limit=100,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        data = getattr(response, "data", None) or []
        if not data:
            break
        for item in data:
            if hasattr(item, "dict"):
                observations.append(_normalize_observation(item.dict()))
            elif hasattr(item, "model_dump"):
                observations.append(_normalize_observation(item.model_dump()))
            else:
                observations.append(_normalize_observation(item))
        meta = getattr(response, "meta", None)
        total_pages = getattr(meta, "total_pages", page) if meta else page
        if page >= total_pages:
            break
        page += 1
    return observations


def profile_from_langfuse(
    *,
    host: str | None = None,
    public_key: str | None = None,
    secret_key: str | None = None,
    lookback_days: int = 30,
    traces: list[dict[str, Any]] | None = None,
    observations: list[dict[str, Any]] | None = None,
    fetch_traces: Callable[..., list[dict[str, Any]]] | None = None,
    fetch_observations: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Derive a WorkloadProfile scan payload from Langfuse project history."""
    if traces is not None and observations is not None:
        return build_profile_from_langfuse_data(traces, observations)

    Langfuse = _require_langfuse()
    resolved_host = host or os.environ.get("LANGFUSE_HOST")
    resolved_public = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY")
    resolved_secret = secret_key or os.environ.get("LANGFUSE_SECRET_KEY")
    if not resolved_public or not resolved_secret:
        raise ValueError(
            "Langfuse credentials required. Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY "
            "or pass public_key/secret_key."
        )

    kwargs: dict[str, Any] = {"public_key": resolved_public, "secret_key": resolved_secret}
    if resolved_host:
        kwargs["host"] = resolved_host
    client = Langfuse(**kwargs)

    now = datetime.now(timezone.utc)
    from_ts = now - timedelta(days=lookback_days)
    trace_fetcher = fetch_traces or _default_fetch_traces
    obs_fetcher = fetch_observations or _default_fetch_observations
    trace_data = trace_fetcher(client, from_timestamp=from_ts, to_timestamp=now)
    observation_data = obs_fetcher(client, from_timestamp=from_ts, to_timestamp=now)
    return build_profile_from_langfuse_data(trace_data, observation_data)
