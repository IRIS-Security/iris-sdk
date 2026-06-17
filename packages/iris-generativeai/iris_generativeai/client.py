"""IRIS wrapper for google-generativeai (legacy Gemini SDK).

google-generativeai is being superseded by google-genai.
Consider migrating to IrisGemini (iris-security-gemini) for new projects.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from iris_core.hitl.handler import enforce_policy_result, finalize_evaluation
from iris_core.cost import record_llm_cost_async
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
from iris_core.models.policy import PolicyResult, Severity, Violation

logger = logging.getLogger("iris.generativeai")
_VAULT_LOCK = threading.Lock()
_HIGH_RISK_DOMAIN = re.compile(r"\b(loan|diagnosis|hiring)\b", re.IGNORECASE)


def _lazy_google_generativeai():
    try:
        return importlib.import_module("google.generativeai")
    except ModuleNotFoundError as exc:
        raise ImportError(
            "google-generativeai is required for IrisGenerativeAI. "
            "Install with: pip install google-generativeai"
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
    engine: CedarEngine, passport: AgentPassport, env: Environment, result: PolicyResult
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


def _extract_text(contents: Any) -> list[str]:
    if contents is None:
        return []
    if isinstance(contents, str):
        return [contents]
    if isinstance(contents, dict):
        values: list[str] = []
        for key in ("text", "content"):
            value = contents.get(key)
            if isinstance(value, str):
                values.append(value)
            elif value is not None:
                values.extend(_extract_text(value))
        if not values:
            for value in contents.values():
                values.extend(_extract_text(value))
        return values
    if isinstance(contents, (list, tuple)):
        values: list[str] = []
        for item in contents:
            values.extend(_extract_text(item))
        return values

    text = getattr(contents, "text", None)
    if isinstance(text, str):
        return [text]
    return []


def _scan_content_violations(contents: Any, passport: AgentPassport) -> list[Violation]:
    prompt = "\n".join(_extract_text(contents))
    if not prompt:
        return []
    if not _HIGH_RISK_DOMAIN.search(prompt):
        return []
    return [
        Violation(
            rule_id="CO-004",
            severity=Severity.HIGH,
            message=(
                f"Gemini prompt for agent '{passport.name}' references a high-risk "
                "consequential domain (loan, diagnosis, or hiring)."
            ),
            compliance_refs=["colorado-ai-act:sb-24-205:consumer-opt-out"],
            remediation=(
                "Set consent evidence in policy context for consequential processing, "
                "or run an IRIS compliance assessment."
            ),
        )
    ]


def _merge_content_violations(
    result: PolicyResult, env: Environment, content_violations: list[Violation]
) -> PolicyResult:
    if not content_violations:
        return result
    violations = list(result.violations) + list(content_violations)
    high = [v for v in violations if v.severity in (Severity.HIGH, Severity.CRITICAL)]
    if high and result.decision == "PERMIT":
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


class IrisGenerativeModel:
    """Governed wrapper around google.generativeai.GenerativeModel."""

    def __init__(
        self,
        passport: AgentPassport,
        model_name: str,
        model: Any,
        engine: CedarEngine,
        vault: EvidenceVault,
        dlp: DLPScanner,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
    ) -> None:
        self._passport = passport
        self._model_name = model_name
        self._model = model
        self._engine = engine
        self._vault = vault
        self._dlp = dlp
        self._user_email = user_email
        self._user_role = user_role

    def _govern(self, contents: Any) -> None:
        env = _current_environment()
        prompt_text = "\n".join(_extract_text(contents))
        dlp_result = enforce_prompt_dlp(
            self._dlp,
            self._vault,
            self._passport,
            env,
            prompt_text,
            resource=f"gemini-api/{self._model_name}",
        )
        content_violations = _scan_content_violations(contents, self._passport)
        user_ctx = UserContext.from_params(self._user_email, self._user_role)
        ctx = EvaluationContext(
            agent_id=self._passport.agent_id,
            action="call",
            resource=f"gemini-api/{self._model_name}",
            resource_type="api",
            environment=env,
            data_classification=self._passport.data_classification.value,
            dlp_prompt_findings=dlp_result.findings,
            additional={
                "model": self._model_name,
                "content_violation_count": len(content_violations),
            },
            **user_ctx.evaluation_fields(),
        )
        result = self._engine.evaluate(self._passport, ctx)
        result = _apply_no_policy_gate(self._engine, self._passport, env, result)
        result = _merge_content_violations(result, env, content_violations)
        with _VAULT_LOCK:
            finalize_evaluation(
                self._passport,
                ctx,
                result,
                self._vault,
                tool_name=f"gemini-api/{self._model_name}",
                action="call",
            )
        enforce_policy_result(result, env)

    def _scan_response(self, response: Any) -> Any:
        env = _current_environment()
        response_text = extract_gemini_response_text(response)
        blocked, _ = handle_response_dlp(
            self._dlp,
            self._vault,
            self._passport,
            env,
            response_text,
            response,
            resource=f"gemini-api/{self._model_name}",
        )
        return blocked

    def generate_content(self, contents: Any, **kwargs: Any) -> Any:
        self._govern(contents)
        env = _current_environment()
        start = time.perf_counter()
        response = self._model.generate_content(contents, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        scanned = self._scan_response(response)
        record_llm_cost_async(
            agent_id=self._passport.agent_id,
            agent_name=self._passport.name,
            provider="google",
            model=self._model_name,
            response=response,
            tool_name=f"gemini-api/{self._model_name}",
            duration_ms=elapsed_ms,
            environment=env.value,
        )
        return scanned

    async def generate_content_async(self, contents: Any = None, **kwargs: Any) -> Any:
        payload = contents if contents is not None else kwargs.get("contents")
        self._govern(payload)
        env = _current_environment()
        start = time.perf_counter()
        if contents is not None:
            response = await self._model.generate_content_async(contents, **kwargs)
        else:
            response = await self._model.generate_content_async(**kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        scanned = self._scan_response(response)
        record_llm_cost_async(
            agent_id=self._passport.agent_id,
            agent_name=self._passport.name,
            provider="google",
            model=self._model_name,
            response=response,
            tool_name=f"gemini-api/{self._model_name}",
            duration_ms=elapsed_ms,
            environment=env.value,
        )
        return scanned

    def start_chat(self, **kwargs: Any) -> "IrisChatSession":
        session = self._model.start_chat(**kwargs)
        return IrisChatSession(model=self, session=session)

    def count_tokens(self, **kwargs: Any) -> Any:
        return self._model.count_tokens(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


class IrisChatSession:
    """Governed wrapper around a legacy Gemini chat session."""

    def __init__(self, model: IrisGenerativeModel, session: Any) -> None:
        self._model = model
        self._session = session

    def send_message(self, content: Any, **kwargs: Any) -> Any:
        self._model._govern(content)
        response = self._session.send_message(content, **kwargs)
        return self._model._scan_response(response)

    async def send_message_async(self, content: Any, **kwargs: Any) -> Any:
        self._model._govern(content)
        response = await self._session.send_message_async(content, **kwargs)
        return self._model._scan_response(response)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


class IrisGenerativeAI:
    """Drop-in wrapper for google-generativeai.

    google-generativeai is being superseded by google-genai.
    Consider migrating to IrisGemini (iris-security-gemini) for new projects.
    """

    def __init__(
        self,
        passport: AgentPassport,
        api_key: Optional[str] = None,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
    ) -> None:
        from iris_core.dev_trust import print_dev_trust_message

        print_dev_trust_message()
        genai = _lazy_google_generativeai()
        self._passport = passport
        self._user_email = user_email
        self._user_role = user_role
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id)
        self._dlp = DLPScanner(passport)
        _load_passport_policy(self._engine, passport)
        genai.configure(api_key=api_key or os.environ["GOOGLE_API_KEY"])
        self._genai = genai

    def GenerativeModel(self, model_name: str, **kwargs: Any) -> IrisGenerativeModel:
        model = self._genai.GenerativeModel(model_name, **kwargs)
        return IrisGenerativeModel(
            passport=self._passport,
            model_name=model_name,
            model=model,
            engine=self._engine,
            vault=self._vault,
            dlp=self._dlp,
            user_email=self._user_email,
            user_role=self._user_role,
        )
