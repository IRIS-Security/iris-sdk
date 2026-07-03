"""Tests for iris-langfuse profile mapping."""

from __future__ import annotations

import pytest

from iris_langfuse._profile import build_profile_from_langfuse_data
from iris_langfuse.reader import (
    _FORBIDDEN_CONTENT_FIELDS,
    _normalize_observation,
    _normalize_trace,
    profile_from_langfuse,
)


FIXTURE_TRACES = [
    {
        "id": "t1",
        "name": "customer-support-agent",
        "tags": ["langchain", "production"],
        "metadata": {"framework": "langchain", "env": "production"},
    },
    {
        "id": "t2",
        "name": "phi-triage",
        "tags": ["hipaa", "patient_id"],
        "metadata": {"integration": "crewai"},
    },
]

FIXTURE_OBSERVATIONS = [
    {"id": "o1", "traceId": "t1", "type": "GENERATION", "model": "gpt-4o", "name": "chat"},
    {"id": "o2", "traceId": "t1", "type": "TOOL_CALL", "model": "gpt-4o", "name": "search_tool"},
    {"id": "o3", "traceId": "t2", "type": "GENERATION", "model": "claude-3-5-sonnet", "name": "triage"},
    {"id": "o4", "traceId": "t2", "type": "TOOL_CALL", "model": "claude-3-5-sonnet", "name": "lookup_mrn"},
]


def test_profile_mapping_from_fixture_traces():
    profile = build_profile_from_langfuse_data(FIXTURE_TRACES, FIXTURE_OBSERVATIONS)
    assert profile["source"] == "sdk_scan"
    assert "gpt-4o" in profile["models"]
    assert "claude-3-5-sonnet" in profile["models"]
    assert "openai" in profile["providers"]
    assert "anthropic" in profile["providers"]
    assert "langchain" in profile["frameworks"]
    assert "crewai" in profile["frameworks"]
    assert "phi" in profile["data_categories"]
    assert profile["autonomy_level"] == "supervised"
    assert profile["customer_facing"] is True
    assert set(profile.keys()) == {
        "source",
        "models",
        "providers",
        "frameworks",
        "data_categories",
        "deployment_regions",
        "agent_count",
        "autonomy_level",
        "customer_facing",
    }


def test_provider_inference():
    profile = build_profile_from_langfuse_data(
        [],
        [{"model": "gemini-1.5-pro", "type": "GENERATION"}],
    )
    assert profile["providers"] == ["google"]


def test_no_prompt_content_read():
    raw_trace = {
        "id": "t1",
        "name": "safe",
        "input": {"messages": [{"role": "user", "content": "secret prompt"}]},
        "output": "secret completion",
        "prompt": "do not read",
        "metadata": {"model": "gpt-4o"},
    }
    raw_obs = {
        "id": "o1",
        "type": "GENERATION",
        "model": "gpt-4o",
        "input": "secret",
        "output": "secret",
        "content": "secret",
    }
    trace = _normalize_trace(raw_trace)
    obs = _normalize_observation(raw_obs)
    for field in _FORBIDDEN_CONTENT_FIELDS:
        assert field not in trace
        assert field not in obs
    assert "input" not in trace and "output" not in trace
    assert "input" not in obs and "output" not in obs

    profile = profile_from_langfuse(
        traces=[trace],
        observations=[obs],
    )
    assert profile["models"] == ["gpt-4o"]


def test_imports_without_langfuse_installed():
    import importlib

    mod = importlib.import_module("iris_langfuse")
    assert hasattr(mod, "profile_from_langfuse")
    with pytest.raises(ImportError, match='iris-langfuse\\[live\\]'):
        profile_from_langfuse(lookback_days=1)
