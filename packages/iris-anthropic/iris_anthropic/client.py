"""Drop-in Anthropic client wrapper with IRIS governance on every messages call."""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, List, Optional

from iris_core.cost import record_llm_cost_async
from iris_core.dlp import DLPScanner
from iris_core.dlp.enforcement import (
    enforce_prompt_dlp,
    extract_anthropic_response_text,
    handle_response_dlp,
)
from iris_core.engine.cedar import CedarEngine
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, UserContext
from iris_anthropic._governance import (
    current_environment,
    enforce_result,
    evaluate_api_call,
    load_passport_policy,
)
from iris_anthropic.guardrails import (
    check_prompt_for_violations,
    effective_data_classification,
)

logger = logging.getLogger("iris.anthropic")


def _lazy_anthropic():
    import anthropic

    return anthropic


def _estimate_call_cost_usd(model_id: Any, messages: Any, system: Any, max_tokens: Any) -> Optional[float]:
    """Pre-call cost estimate for the budget check — never raises; a governed
    call must never fail because cost estimation failed."""
    if not model_id:
        return None
    try:
        from iris_core.cost.counter import TokenCounter
        from iris_core.cost.pricing import PricingRegistry

        input_tokens = TokenCounter().count_input(
            provider="anthropic", model=str(model_id), messages=messages, system=system
        )
        return PricingRegistry().calculate_cost(
            "anthropic", str(model_id), input_tokens, int(max_tokens or 0)
        )
    except Exception:
        return None


def _extract_prompt_text(kwargs: dict) -> str:
    parts: List[str] = []
    system = kwargs.get("system")
    if system:
        if isinstance(system, str):
            parts.append(system)
        elif isinstance(system, list):
            for block in system:
                if isinstance(block, dict):
                    text = block.get("text") or block.get("content")
                    if text:
                        parts.append(str(text))
    for msg in kwargs.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text") or block.get("content")
                    if text:
                        parts.append(str(text))
    return "\n".join(parts)


class _IrisAnthropicClientBase:
    _passport: AgentPassport
    _engine: CedarEngine
    _vault: EvidenceVault
    _dlp: DLPScanner
    _user_email: Optional[str] = None
    _user_role: Optional[str] = None
    _user_context: Optional[UserContext] = None
    _user_work_authorization: Optional[str] = None
    _auto_fallback: bool = True
    _hitl_approved: bool = False


class _GovernedMessagesBase:
    """Uses the parent client so engine/vault stay in sync when replaced in tests."""

    def __init__(self, parent: _IrisAnthropicClientBase, messages_resource: Any):
        self._parent = parent
        self._messages = messages_resource

    @property
    def _passport(self) -> AgentPassport:
        return self._parent._passport

    @property
    def _engine(self) -> CedarEngine:
        return self._parent._engine

    @property
    def _vault(self) -> EvidenceVault:
        return self._parent._vault

    def _govern_kwargs(self, kwargs: dict) -> None:
        from iris_core.engine.model_governance import resolve_fallback_model

        env = current_environment()
        call_user_context = kwargs.pop("user_context", None) or self._parent._user_context
        require_hitl = bool(kwargs.pop("require_hitl", False))
        require_hitl_reason = kwargs.pop("require_hitl_reason", None)
        messages = kwargs.get("messages")
        model_id = kwargs.get("model")
        auto_fallback_applied = False
        if model_id and self._parent._auto_fallback:
            self._engine.reload_model_governance()
            fallback = resolve_fallback_model(
                str(model_id),
                self._engine._model_registry,
                self._engine._directive_registry,
            )
            if fallback and fallback != model_id:
                msg = (
                    f"[IRIS] Model '{model_id}' is suspended — "
                    f"auto-fallback to '{fallback}'"
                )
                logger.warning(msg)
                print(msg, file=sys.stderr)
                kwargs["model"] = fallback
                model_id = fallback
                auto_fallback_applied = True

        prompt = _extract_prompt_text(kwargs)
        dlp_result = enforce_prompt_dlp(
            self._parent._dlp,
            self._vault,
            self._passport,
            env,
            prompt,
            resource="anthropic-api",
        )
        prompt_violations = check_prompt_for_violations(prompt, self._passport)
        data_classification = effective_data_classification(prompt, self._passport)
        additional = {
            "model": kwargs.get("model"),
            "max_tokens": kwargs.get("max_tokens"),
            "prompt_violation_count": len(prompt_violations),
        }
        if prompt_violations:
            additional["prompt_violations"] = [v.rule_id for v in prompt_violations]
        if self._passport.budget_config and self._passport.budget_config.enabled:
            additional["estimated_call_cost_usd"] = _estimate_call_cost_usd(
                model_id, messages, kwargs.get("system"), kwargs.get("max_tokens")
            )

        result = evaluate_api_call(
            self._engine,
            self._vault,
            self._passport,
            env,
            data_classification=data_classification,
            prompt_violations=prompt_violations,
            additional=additional,
            dlp_prompt_findings=dlp_result.findings,
            user_email=self._parent._user_email,
            user_role=self._parent._user_role,
            user_context=call_user_context,
            model_id=str(model_id) if model_id else None,
            user_work_authorization=self._parent._user_work_authorization,
            hitl_approved=self._parent._hitl_approved,
            auto_fallback_applied=auto_fallback_applied,
            require_hitl=require_hitl,
            require_hitl_reason=require_hitl_reason,
            messages=messages,
        )
        enforce_result(result, env)

    def _scan_response(self, response: Any) -> Any:
        env = current_environment()
        response_text = extract_anthropic_response_text(response)
        blocked, _ = handle_response_dlp(
            self._parent._dlp,
            self._vault,
            self._passport,
            env,
            response_text,
            response,
            resource="anthropic-api",
        )
        return blocked


class IrisMessagesResource(_GovernedMessagesBase):
    def create(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        model = kwargs.get("model", "unknown")
        env = current_environment()
        start = time.perf_counter()
        response = self._messages.create(**kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        scanned = self._scan_response(response)
        record_llm_cost_async(
            agent_id=self._passport.agent_id,
            agent_name=self._passport.name,
            provider="anthropic",
            model=model,
            response=response,
            tool_name="anthropic-api",
            duration_ms=elapsed_ms,
            environment=env.value,
        )
        return scanned

    def stream(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        return self._messages.stream(**kwargs)


class IrisMessagesResourceAsync(_GovernedMessagesBase):
    async def create(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        model = kwargs.get("model", "unknown")
        env = current_environment()
        start = time.perf_counter()
        response = await self._messages.create(**kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        scanned = self._scan_response(response)
        record_llm_cost_async(
            agent_id=self._passport.agent_id,
            agent_name=self._passport.name,
            provider="anthropic",
            model=model,
            response=response,
            tool_name="anthropic-api",
            duration_ms=elapsed_ms,
            environment=env.value,
        )
        return scanned

    async def stream(self, **kwargs: Any) -> Any:
        self._govern_kwargs(kwargs)
        return await self._messages.stream(**kwargs)


class IrisAnthropic(_IrisAnthropicClientBase):
    """
    Drop-in replacement for anthropic.Anthropic() with IRIS governance.

    Pass an AgentPassport and the same kwargs you would give Anthropic().
    All attributes not defined here are proxied to the underlying client.
    """

    def __init__(
        self,
        passport: AgentPassport,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        user_context: Optional[UserContext] = None,
        user_work_authorization: Optional[str] = None,
        auto_fallback: bool = True,
        hitl_approved: bool = False,
        **anthropic_kwargs: Any,
    ):
        from iris_core.dev_trust import print_dev_trust_message

        print_dev_trust_message()
        anthropic = _lazy_anthropic()
        self._passport = passport
        self._user_email = user_email or os.environ.get("IRIS_USER_EMAIL")
        self._user_role = user_role or os.environ.get("IRIS_USER_ROLE")
        self._user_context = user_context
        self._user_work_authorization = (
            user_work_authorization or os.environ.get("IRIS_USER_WORK_AUTHORIZATION")
        )
        self._auto_fallback = auto_fallback
        self._hitl_approved = hitl_approved
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id)
        self._dlp = DLPScanner(passport)
        load_passport_policy(self._engine, passport)
        self._client = anthropic.Anthropic(**anthropic_kwargs)
        self._messages_resource = IrisMessagesResource(self, self._client.messages)

    @property
    def messages(self) -> IrisMessagesResource:
        return self._messages_resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class IrisAnthropicAsync(_IrisAnthropicClientBase):
    """Async drop-in replacement for anthropic.AsyncAnthropic()."""

    def __init__(
        self,
        passport: AgentPassport,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        user_context: Optional[UserContext] = None,
        user_work_authorization: Optional[str] = None,
        auto_fallback: bool = True,
        hitl_approved: bool = False,
        **anthropic_kwargs: Any,
    ):
        anthropic = _lazy_anthropic()
        self._passport = passport
        self._user_email = user_email or os.environ.get("IRIS_USER_EMAIL")
        self._user_role = user_role or os.environ.get("IRIS_USER_ROLE")
        self._user_context = user_context
        self._user_work_authorization = (
            user_work_authorization or os.environ.get("IRIS_USER_WORK_AUTHORIZATION")
        )
        self._auto_fallback = auto_fallback
        self._hitl_approved = hitl_approved
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id)
        self._dlp = DLPScanner(passport)
        load_passport_policy(self._engine, passport)
        self._client = anthropic.AsyncAnthropic(**anthropic_kwargs)
        self._messages_resource = IrisMessagesResourceAsync(self, self._client.messages)

    @property
    def messages(self) -> IrisMessagesResourceAsync:
        return self._messages_resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
