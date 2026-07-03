"""Parse LiteLLM config.yaml model_list safely."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from iris_litellm._profile import build_profile_from_config_entries


def parse_litellm_config(path: str | Path) -> list[dict[str, Any]]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"LiteLLM config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("LiteLLM config must be a YAML mapping")
    model_list = raw.get("model_list") or []
    if not isinstance(model_list, list):
        raise ValueError("model_list must be a list")
    entries: list[dict[str, Any]] = []
    for item in model_list:
        if isinstance(item, dict):
            entries.append(item)
    return entries


def profile_from_litellm_config(path: str | Path) -> dict[str, Any]:
    """Derive a WorkloadProfile scan payload from a static LiteLLM config.yaml."""
    entries = parse_litellm_config(path)
    return build_profile_from_config_entries(entries)
