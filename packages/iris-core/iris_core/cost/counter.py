"""Token counting for LLM calls — provider-specific where available."""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger("iris.cost")


class TokenCounter:
    """Count input and output tokens for LLM API calls."""

    def __init__(self) -> None:
        self._last_is_estimated = False

    @property
    def last_is_estimated(self) -> bool:
        return self._last_is_estimated

    def _estimate_tokens(self, content: Any) -> int:
        self._last_is_estimated = True
        text = str(content)
        return max(1, len(text) // 4)

    def _log_estimation_note(self, provider: str, model: str) -> None:
        logger.info(
            "Using estimated token count for %s/%s. "
            "Install tiktoken for more accurate counting: pip install tiktoken",
            provider,
            model,
        )

    def count_input(
        self,
        provider: str,
        model: str,
        messages: Any,
        system: Optional[str] = None,
    ) -> int:
        """Count input tokens before an API call."""
        self._last_is_estimated = False
        provider_norm = provider.strip().lower()
        content_parts = []
        if system:
            content_parts.append(system)
        content_parts.append(str(messages))
        combined = "\n".join(content_parts)

        if provider_norm == "anthropic":
            try:
                import anthropic

                client = anthropic.Anthropic()
                count = client.messages.count_tokens(
                    model=model,
                    messages=messages if isinstance(messages, list) else [{"role": "user", "content": str(messages)}],
                    system=system,
                )
                return int(getattr(count, "input_tokens", count))
            except Exception:
                self._log_estimation_note(provider, model)
                return self._estimate_tokens(combined)

        if provider_norm == "openai":
            try:
                import tiktoken

                encoding = tiktoken.encoding_for_model(model)
                return len(encoding.encode(combined))
            except Exception:
                self._log_estimation_note(provider, model)
                return self._estimate_tokens(combined)

        if provider_norm in ("google", "gemini"):
            try:
                import google.genai as genai

                client = genai.Client()
                result = client.models.count_tokens(model=model, contents=messages)
                return int(getattr(result, "total_tokens", getattr(result, "token_count", 0)))
            except Exception:
                self._log_estimation_note(provider, model)
                return self._estimate_tokens(combined)

        self._log_estimation_note(provider, model)
        return self._estimate_tokens(combined)

    def count_output(self, provider: str, model: str, response: Any) -> int:
        """Extract output token count from an API response."""
        self._last_is_estimated = False
        provider_norm = provider.strip().lower()

        usage = getattr(response, "usage", None)
        if usage is not None:
            if provider_norm == "anthropic":
                tokens = getattr(usage, "output_tokens", None)
                if tokens is not None:
                    return int(tokens)
            if provider_norm == "openai":
                tokens = getattr(usage, "completion_tokens", None)
                if tokens is not None:
                    return int(tokens)

        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata is not None:
            tokens = getattr(usage_metadata, "candidates_token_count", None)
            if tokens is not None:
                return int(tokens)

        if isinstance(response, dict):
            usage_dict = response.get("usage") or response.get("usage_metadata") or {}
            for key in ("output_tokens", "completion_tokens", "candidates_token_count"):
                if key in usage_dict:
                    return int(usage_dict[key])

        self._log_estimation_note(provider, model)
        return self._estimate_tokens(response)

    def count_from_response(self, response: Any, provider: str = "", model: str = "") -> Tuple[int, int]:
        """Extract input and output token counts from a response object."""
        self._last_is_estimated = False
        input_tokens: Optional[int] = None
        output_tokens: Optional[int] = None

        usage = getattr(response, "usage", None)
        if usage is not None:
            input_tokens = (
                getattr(usage, "input_tokens", None)
                or getattr(usage, "prompt_tokens", None)
            )
            output_tokens = (
                getattr(usage, "output_tokens", None)
                or getattr(usage, "completion_tokens", None)
            )

        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata is not None:
            if input_tokens is None:
                input_tokens = getattr(usage_metadata, "prompt_token_count", None)
            if output_tokens is None:
                output_tokens = getattr(usage_metadata, "candidates_token_count", None)

        if isinstance(response, dict):
            usage_dict = response.get("usage") or response.get("usage_metadata") or {}
            if input_tokens is None:
                input_tokens = usage_dict.get("input_tokens") or usage_dict.get("prompt_tokens") or usage_dict.get("prompt_token_count")
            if output_tokens is None:
                output_tokens = (
                    usage_dict.get("output_tokens")
                    or usage_dict.get("completion_tokens")
                    or usage_dict.get("candidates_token_count")
                )

        if input_tokens is not None and output_tokens is not None:
            return int(input_tokens), int(output_tokens)

        if output_tokens is not None and input_tokens is None:
            self._last_is_estimated = True
            return 0, int(output_tokens)

        if input_tokens is not None and output_tokens is None:
            estimated_output = self.count_output(provider, model, response)
            return int(input_tokens), estimated_output

        self._log_estimation_note(provider, model)
        estimated = self._estimate_tokens(response)
        self._last_is_estimated = True
        return estimated, estimated
