"""Tests for iris-openrouter — offline, against fixture activity JSON.

The HTTP call is always mocked; no test reaches openrouter.ai.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from iris_openrouter import reader
from iris_openrouter._profile import build_profile_from_activity, summarize_activity
from iris_openrouter.reader import (
    MANAGEMENT_KEYS_URL,
    WRONG_KEY_TYPE_MESSAGE,
    ManagementKeyError,
    OpenRouterActivityError,
    fetch_activity,
    parse_activity_response,
    profile_from_openrouter,
)

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "examples" / "sample_activity.json").read_text()
)
VALID_LOOKING_KEY = "sk-or-v1-0123456789abcdef"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Fail loudly if anything constructs a real (non-mocked) HTTP transport."""

    def _blocked(*args, **kwargs):
        raise AssertionError("real network call attempted in tests")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)
    monkeypatch.delenv("OPENROUTER_MANAGEMENT_KEY", raising=False)


def _mock_openrouter(monkeypatch, status: int, body: dict) -> list[httpx.Request]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        reader,
        "_make_client",
        lambda timeout: httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout),
    )
    return calls


# --- model / provider extraction -------------------------------------------


def test_profile_extracts_distinct_models_and_serving_providers():
    profile = build_profile_from_activity(parse_activity_response(FIXTURE))
    assert profile["models"] == [
        "anthropic/claude-sonnet-4",
        "meta-llama/llama-3.3-70b-instruct",
        "openai/gpt-4.1",
    ]
    # provider_name is the serving provider; Together serves the Llama model.
    assert profile["providers"] == ["anthropic", "openai", "together"]
    assert profile["frameworks"] == ["openrouter"]


def test_zero_request_rows_are_not_counted_as_running():
    profile = build_profile_from_activity(parse_activity_response(FIXTURE))
    assert "mistralai/mistral-large" not in profile["models"]
    assert "mistral" not in profile["providers"]


def test_profile_matches_workload_profile_shape():
    profile = build_profile_from_activity(parse_activity_response(FIXTURE))
    assert set(profile) == {
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
    assert profile["source"] == "sdk_scan"
    assert profile["agent_count"] == 1


def test_empty_activity_yields_empty_profile():
    profile = build_profile_from_activity([])
    assert profile["models"] == []
    assert profile["providers"] == []
    assert profile["frameworks"] == []
    assert profile["agent_count"] == 0


def test_provider_falls_back_to_shared_model_inference_when_missing():
    rows = [{"model": "anthropic/claude-3.5-sonnet", "requests": 3}]
    assert build_profile_from_activity(rows)["providers"] == ["anthropic"]


def test_cost_and_unknown_fields_are_dropped():
    rows = parse_activity_response(FIXTURE)
    assert all("usage" not in row and "byok_usage_inference" not in row for row in rows)


def test_summarize_activity_reports_volume_by_requests():
    summary = summarize_activity(parse_activity_response(FIXTURE))
    assert [item["model"] for item in summary] == [
        "anthropic/claude-sonnet-4",
        "openai/gpt-4.1",
        "meta-llama/llama-3.3-70b-instruct",
    ]
    assert summary[0] == {
        "model": "anthropic/claude-sonnet-4",
        "provider": "anthropic",
        "requests": 77,
        "prompt_tokens": 30500,
        "completion_tokens": 9100,
    }


def test_unrecognized_response_shape_raises():
    with pytest.raises(OpenRouterActivityError):
        parse_activity_response({"items": []})


# --- live-call path (mocked) -----------------------------------------------


def test_fetch_activity_calls_activity_endpoint_with_bearer_key(monkeypatch):
    calls = _mock_openrouter(monkeypatch, 200, FIXTURE)
    profile = profile_from_openrouter(VALID_LOOKING_KEY)
    assert len(calls) == 1
    assert str(calls[0].url) == "https://openrouter.ai/api/v1/activity"
    assert calls[0].headers["Authorization"] == f"Bearer {VALID_LOOKING_KEY}"
    assert profile["providers"] == ["anthropic", "openai", "together"]


def test_key_read_from_env_var(monkeypatch):
    calls = _mock_openrouter(monkeypatch, 200, FIXTURE)
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_KEY", VALID_LOOKING_KEY)
    fetch_activity()
    assert calls[0].headers["Authorization"] == f"Bearer {VALID_LOOKING_KEY}"


# --- wrong-key-type handling -------------------------------------------------


@pytest.mark.parametrize(
    "bad_key",
    ["Bearer sk-or-v1-abc", "sk-or-v1-abc def", '"sk-or-v1-abc"', "sk-or-v1-\nabc"],
)
def test_malformed_key_fails_fast_with_custom_message_and_no_request(monkeypatch, bad_key):
    calls = _mock_openrouter(monkeypatch, 200, FIXTURE)
    with pytest.raises(ManagementKeyError) as excinfo:
        fetch_activity(bad_key)
    assert WRONG_KEY_TYPE_MESSAGE in str(excinfo.value)
    assert calls == []


@pytest.mark.parametrize(
    ("status", "openrouter_message"),
    [
        (403, "Only management keys can perform this operation"),
        (401, "Missing Authentication header"),
    ],
)
def test_auth_rejection_shows_iris_message_not_openrouters(monkeypatch, status, openrouter_message):
    calls = _mock_openrouter(
        monkeypatch, status, {"error": {"code": status, "message": openrouter_message}}
    )
    with pytest.raises(ManagementKeyError) as excinfo:
        fetch_activity(VALID_LOOKING_KEY)
    message = str(excinfo.value)
    assert len(calls) == 1
    assert message.startswith(WRONG_KEY_TYPE_MESSAGE)
    assert MANAGEMENT_KEYS_URL in message
    assert openrouter_message not in message


def test_missing_key_is_reported_without_a_request(monkeypatch):
    calls = _mock_openrouter(monkeypatch, 200, FIXTURE)
    with pytest.raises(ManagementKeyError, match="OPENROUTER_MANAGEMENT_KEY"):
        fetch_activity()
    assert calls == []


def test_other_http_errors_are_not_reported_as_key_problems(monkeypatch):
    _mock_openrouter(monkeypatch, 500, {"error": {"code": 500, "message": "boom"}})
    with pytest.raises(OpenRouterActivityError, match="HTTP 500"):
        fetch_activity(VALID_LOOKING_KEY)


# --- no network when working from fixtures -----------------------------------


def test_fixture_mapping_makes_no_network_call(monkeypatch):
    def _no_client(*args, **kwargs):
        raise AssertionError("HTTP client constructed during fixture mapping")

    monkeypatch.setattr(reader, "_make_client", _no_client)
    monkeypatch.setattr(httpx, "Client", _no_client)
    profile = build_profile_from_activity(parse_activity_response(FIXTURE))
    assert profile["models"]
