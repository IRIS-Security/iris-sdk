"""Static pricing registry for LLM token cost estimation."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

logger = logging.getLogger("iris.cost")

DEFAULT_PRICING: Dict[str, Tuple[float, float]] = {
    # Anthropic
    "anthropic/claude-opus-4-6": (15.00, 75.00),
    "anthropic/claude-sonnet-4-6": (3.00, 15.00),
    "anthropic/claude-haiku-4-5": (0.80, 4.00),
    # OpenAI
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4-turbo": (10.00, 30.00),
    "openai/o1": (15.00, 60.00),
    "openai/o1-mini": (3.00, 12.00),
    # Google
    "google/gemini-2.0-flash": (0.10, 0.40),
    "google/gemini-2.0-pro": (1.25, 5.00),
    "google/gemini-1.5-pro": (1.25, 5.00),
    "google/gemini-1.5-flash": (0.075, 0.30),
    # Mistral
    "mistral/mistral-large-latest": (2.00, 6.00),
    "mistral/mistral-small-latest": (0.20, 0.60),
    "mistral/codestral-latest": (0.20, 0.60),
    # Groq
    "groq/llama-3.3-70b-versatile": (0.59, 0.79),
    "groq/llama-3.1-8b-instant": (0.05, 0.08),
    "groq/mixtral-8x7b-32768": (0.24, 0.24),
    # Cohere
    "cohere/command-r-plus": (2.50, 10.00),
    "cohere/command-r": (0.15, 0.60),
    # Ollama (local — always free)
    "ollama/*": (0.00, 0.00),
}

OVERRIDES_PATH = Path.home() / ".iris" / "pricing-overrides.yaml"
_VERSION_SUFFIX = re.compile(r"-\d{4}(-\d{2})?(-\d{2})?$|-v\d+(\.\d+)*$", re.IGNORECASE)


def overrides_path() -> Path:
    return Path.home() / ".iris" / "pricing-overrides.yaml"


class PricingRegistry:
    """Lookup table of cost per 1M tokens for major LLM providers."""

    def __init__(self, pricing: Optional[Dict[str, Tuple[float, float]]] = None) -> None:
        self._pricing: Dict[str, Tuple[float, float]] = dict(DEFAULT_PRICING)
        if pricing:
            self._pricing.update(pricing)
        path = overrides_path()
        if path.exists():
            try:
                override_registry = PricingRegistry.from_yaml(path)
                self._pricing.update(override_registry._pricing)
            except Exception as exc:
                logger.warning("Failed to load pricing overrides from %s: %s", path, exc)

    @staticmethod
    def _normalize_model(model: str) -> str:
        normalized = model.strip().lower()
        normalized = _VERSION_SUFFIX.sub("", normalized)
        return normalized

    @staticmethod
    def _model_key(provider: str, model: str) -> str:
        provider_norm = provider.strip().lower()
        model_norm = PricingRegistry._normalize_model(model)
        return f"{provider_norm}/{model_norm}"

    def get_price(self, provider: str, model: str) -> Tuple[float, float]:
        """Return (input_cost_per_1m, output_cost_per_1m) in USD."""
        key = self._model_key(provider, model)
        if key in self._pricing:
            return self._pricing[key]

        provider_norm = provider.strip().lower()
        if provider_norm == "ollama":
            return self._pricing.get("ollama/*", (0.0, 0.0))

        for registry_key, price in self._pricing.items():
            if registry_key.endswith("/*") and registry_key.startswith(f"{provider_norm}/"):
                return price

        model_norm = self._normalize_model(model)
        for registry_key, price in self._pricing.items():
            if not registry_key.startswith(f"{provider_norm}/"):
                continue
            registry_model = registry_key.split("/", 1)[1]
            if model_norm.startswith(registry_model) or registry_model in model_norm:
                return price

        logger.warning(
            "Unknown model pricing for %s/%s — using $0.00. "
            "Add a custom override via iris cost pricing --update.",
            provider,
            model,
        )
        return (0.0, 0.0)

    def calculate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Return total USD cost for a single LLM call."""
        input_price, output_price = self.get_price(provider, model)
        return (input_tokens / 1_000_000 * input_price) + (
            output_tokens / 1_000_000 * output_price
        )

    def update_pricing(
        self,
        model_key: str,
        input_per_1m: float,
        output_per_1m: float,
    ) -> None:
        """Persist a custom pricing override to ~/.iris/pricing-overrides.yaml."""
        path = overrides_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: Dict[str, dict] = {}
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}
            existing = data.get("pricing", {}) or {}

        existing[model_key] = {
            "input_per_1m": input_per_1m,
            "output_per_1m": output_per_1m,
        }
        path.write_text(
            yaml.dump({"pricing": existing}, default_flow_style=False, sort_keys=False)
        )
        self._pricing[model_key] = (input_per_1m, output_per_1m)

    @classmethod
    def from_yaml(cls, path: Path) -> "PricingRegistry":
        """Load custom pricing from a YAML file."""
        data = yaml.safe_load(path.read_text()) or {}
        pricing_section = data.get("pricing", {}) or {}
        overrides: Dict[str, Tuple[float, float]] = {}
        for model_key, rates in pricing_section.items():
            if not isinstance(rates, dict):
                continue
            overrides[str(model_key)] = (
                float(rates.get("input_per_1m", 0.0)),
                float(rates.get("output_per_1m", 0.0)),
            )
        return cls(pricing=overrides)

    def all_pricing(self) -> Dict[str, Tuple[float, float]]:
        """Return the full pricing table (built-in + overrides)."""
        return dict(self._pricing)
