"""Tests for iris-litellm profile mapping."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from iris.scan import infer_provider_from_model
from iris_litellm._profile import build_profile_from_config_entries
from iris_litellm.config_reader import profile_from_litellm_config
from iris_litellm.proxy_reader import profile_from_litellm_proxy


FIXTURE_CONFIG = """\
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: gpt-4o
      api_key: os.environ/OPENAI_API_KEY
  - model_name: claude-primary
    litellm_params:
      model: claude-3-5-sonnet-20241022
      custom_llm_provider: anthropic
  - model_name: gemini-flash
    litellm_params:
      model: gemini/gemini-1.5-flash
"""


def test_config_yaml_to_profile(tmp_path: Path):
    config_path = tmp_path / "litellm.config.yaml"
    config_path.write_text(FIXTURE_CONFIG, encoding="utf-8")
    profile = profile_from_litellm_config(config_path)
    assert profile["source"] == "sdk_scan"
    assert "gpt-4o" in profile["models"]
    assert "claude-3-5-sonnet-20241022" in profile["models"]
    assert "gemini/gemini-1.5-flash" in profile["models"]
    assert "openai" in profile["providers"]
    assert "anthropic" in profile["providers"]
    assert "google" in profile["providers"]
    assert profile["frameworks"] == ["litellm"]


def test_proxy_model_info_to_profile():
    model_info = [
        {"model_name": "gpt-4o-mini", "litellm_provider": "openai"},
        {"model_name": "claude-3-haiku", "litellm_provider": "anthropic"},
    ]
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": model_info}
    mock_response.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_response

    profile = profile_from_litellm_proxy(
        "https://litellm.example.com",
        api_key="test-key",
        model_info=model_info,
        spend_models=["gpt-4o-mini"],
        client=mock_client,
    )
    assert "gpt-4o-mini" in profile["models"]
    assert "claude-3-haiku" in profile["models"]
    assert "openai" in profile["providers"]


def test_provider_inference_shared_with_scan():
    assert infer_provider_from_model("gpt-4o") == "openai"
    assert infer_provider_from_model("claude-3-opus") == "anthropic"
    profile = build_profile_from_config_entries(
        [{"litellm_params": {"model": "gemini-1.5-pro"}}]
    )
    assert profile["providers"] == ["google"]


def test_imports_without_litellm_installed():
    import importlib

    mod = importlib.import_module("iris_litellm")
    assert hasattr(mod, "profile_from_litellm_config")
    assert hasattr(mod, "profile_from_litellm_proxy")
