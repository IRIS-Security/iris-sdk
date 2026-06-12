"""Drop-in Google GenAI client wrapper with IRIS governance."""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from iris import IrisViolationError
from iris_core.dlp import DLPScanner
from iris_core.dlp.enforcement import (
    enforce_prompt_dlp,
    extract_gemini_response_text,
    handle_response_dlp,
)
from iris_core.engine.cedar import CedarEngine, EvaluationContext
from iris_core.rbac.context import UserContext
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment
from iris_core.models.policy import PolicyResult, Severity

from iris_gemini.guardrails import _extract_text, scan_gemini_content

logger = logging.getLogger("iris.gemini")
_VAULT_LOCK = threading.Lock()


def _lazy_genai():
    try:
        return importlib.import_module("google.genai")
    except ModuleNotFoundError as exc:
        raise ImportError(
            "google-genai is required for IrisGemini. Install with: pip install google-genai"
        ) from exc


def _current_environment() -> Environment:
    return Environment(os.environ.get("IRIS_ENV", "dev"))


def _load_passport_policy(engine: CedarEngine, passport: AgentPassport) -> None:
    if not passport.policy_ref:
        return
    policy_path = Path(passport.policy_ref)
    if not policy_path.is_absolute():
        policy_path = Path.cwd() / policy_path
    if policy_path.exists():
        engine.load_policy_file(passport.agent_id, policy_path)


def _has_policy_loaded(engine: CedarEngine, passport: AgentPassport) -> bool:
    return bool(engine._policy_cache.get(passport.agent_id))


def _apply_no_policy_gate(
    engine: CedarEngine,
    passport: AgentPassport,
    env: Environment,
    result: PolicyResult,
) -> PolicyResult:
    if _has_policy_loaded(engine, passport):
        return result
    if env in (Environment.DEV, Environment.TEST) and result.decision == "DENY":
        return PolicyResult(
            decision="PERMIT_WITH_WARNINGS",
            violations=result.violations,
            agent_id=result.agent_id,
            action=result.action,
            resource=result.resource,
            environment=result.environment,
        )
    return result


def _merge_content_violations(
    result: PolicyResult, env: Environment, content_violations: list
) -> PolicyResult:
    if not content_violations:
        return result
    violations = list(result.violations) + list(content_violations)
    critical = [v for v in violations if v.severity == Severity.CRITICAL]
    high = [v for v in violations if v.severity in (Severity.HIGH, Severity.CRITICAL)]
    if critical:
        decision = "DENY"
    elif high and result.decision == "PERMIT":
        decision = "PERMIT_WITH_WARNINGS" if env in (Environment.DEV, Environment.TEST) else "DENY"
    elif violations and result.decision == "PERMIT":
        decision = "PERMIT_WITH_WARNINGS"
    else:
        decision = result.decision
    return PolicyResult(
        decision=decision,
        violations=violations,
        agent_id=result.agent_id,
        action=result.action,
        resource=result.resource,
        environment=result.environment,
    )


def _enforce_result(result: PolicyResult, env: Environment) -> None:
    if result.decision == "DENY":
        if env in (Environment.DEV, Environment.TEST):
            for violation in result.violations:
                msg = (
                    f"[IRIS WARNING] {violation.message} "
                    f"Remediation: {violation.remediation}"
                )
                logger.warning(msg)
                print(msg, file=sys.stderr)
            return
        raise IrisViolationError(result)
    if result.decision == "PERMIT_WITH_WARNINGS":
        for violation in result.violations:
            msg = f"[IRIS WARNING] {violation.message} Remediation: {violation.remediation}"
            logger.warning(msg)
            print(msg, file=sys.stderr)


class _IrisGeminiBase:
    _passport: AgentPassport
    _engine: CedarEngine
    _vault: EvidenceVault
    _dlp: DLPScanner
    _user_email: Optional[str] = None
    _user_role: Optional[str] = None


class IrisModelsResource:
    """Governed wrapper around google.genai client.models."""

    def __init__(self, parent: _IrisGeminiBase, models_resource: Any):
        self._parent = parent
        self._models = models_resource

    @property
    def _passport(self) -> AgentPassport:
        return self._parent._passport

    @property
    def _engine(self) -> CedarEngine:
        return self._parent._engine

    @property
    def _vault(self) -> EvidenceVault:
        return self._parent._vault

    def _govern(self, model: Optional[str], contents: Any, kwargs: dict) -> None:
        env = _current_environment()
        model_name = model or kwargs.get("model") or "unknown-model"
        request_contents = contents if contents is not None else kwargs.get("contents")
        prompt_text = "\n".join(_extract_text(request_contents))
        dlp_result = enforce_prompt_dlp(
            self._parent._dlp,
            self._vault,
            self._passport,
            env,
            prompt_text,
            resource=f"gemini-api/{model_name}",
        )
        content_violations = scan_gemini_content(request_contents, self._passport)
        user_ctx = UserContext.from_params(self._parent._user_email, self._parent._user_role)
        ctx = EvaluationContext(
            agent_id=self._passport.agent_id,
            action="call",
            resource=f"gemini-api/{model_name}",
            resource_type="api",
            environment=env,
            data_classification=self._passport.data_classification.value,
            dlp_prompt_findings=dlp_result.findings,
            additional={
                "model": model_name,
                "content_violation_count": len(content_violations),
            },
            **user_ctx.evaluation_fields(),
        )
        result = self._engine.evaluate(self._passport, ctx)
        result = _apply_no_policy_gate(self._engine, self._passport, env, result)
        result = _merge_content_violations(result, env, content_violations)
        with _VAULT_LOCK:
            self._vault.record(ctx, result)
        _enforce_result(result, env)

    def _scan_response(self, response: Any) -> Any:
        env = _current_environment()
        response_text = extract_gemini_response_text(response)
        blocked, _ = handle_response_dlp(
            self._parent._dlp,
            self._vault,
            self._passport,
            env,
            response_text,
            response,
            resource="gemini-api",
        )
        return blocked

    def generate_content(self, model: Any = None, contents: Any = None, **kwargs: Any) -> Any:
        self._govern(model, contents, kwargs)
        if model is not None:
            kwargs["model"] = model
        if contents is not None:
            kwargs["contents"] = contents
        response = self._models.generate_content(**kwargs)
        return self._scan_response(response)

    def generate_content_stream(
        self, model: Any = None, contents: Any = None, **kwargs: Any
    ) -> Any:
        self._govern(model, contents, kwargs)
        if model is not None:
            kwargs["model"] = model
        if contents is not None:
            kwargs["contents"] = contents
        return self._models.generate_content_stream(**kwargs)

    async def generate_content_async(
        self, model: Any = None, contents: Any = None, **kwargs: Any
    ) -> Any:
        self._govern(model, contents, kwargs)
        if model is not None:
            kwargs["model"] = model
        if contents is not None:
            kwargs["contents"] = contents
        response = await self._models.generate_content_async(**kwargs)
        return self._scan_response(response)

    async def generate_content_stream_async(
        self, model: Any = None, contents: Any = None, **kwargs: Any
    ) -> Any:
        self._govern(model, contents, kwargs)
        if model is not None:
            kwargs["model"] = model
        if contents is not None:
            kwargs["contents"] = contents
        return await self._models.generate_content_stream_async(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._models, name)


class IrisGemini(_IrisGeminiBase):
    """Drop-in replacement for google.genai.Client()."""

    def __init__(
        self,
        passport: AgentPassport,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        **genai_kwargs: Any,
    ):
        from iris_core.dev_trust import print_dev_trust_message

        print_dev_trust_message()
        genai = _lazy_genai()
        self._passport = passport
        self._user_email = user_email
        self._user_role = user_role
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id)
        self._dlp = DLPScanner(passport)
        _load_passport_policy(self._engine, passport)
        self._client = genai.Client(**genai_kwargs)
        self._models_resource = IrisModelsResource(self, self._client.models)

    @property
    def models(self) -> IrisModelsResource:
        return self._models_resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class IrisGeminiAsync(_IrisGeminiBase):
    """Async drop-in wrapper for google.genai.Client async methods."""

    def __init__(
        self,
        passport: AgentPassport,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        **genai_kwargs: Any,
    ):
        genai = _lazy_genai()
        self._passport = passport
        self._user_email = user_email
        self._user_role = user_role
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id)
        self._dlp = DLPScanner(passport)
        _load_passport_policy(self._engine, passport)
        self._client = genai.Client(**genai_kwargs)
        self._models_resource = IrisModelsResource(self, self._client.models)

    @property
    def models(self) -> IrisModelsResource:
        return self._models_resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
