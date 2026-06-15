"""Shared IRIS evaluation helpers for Anthropic SDK integration."""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import List, Optional

from iris import IrisViolationError
from iris_core.engine.cedar import CedarEngine, EvaluationContext
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment, UserContext
from iris_core.models.policy import PolicyResult, Violation

logger = logging.getLogger("iris.anthropic")

_VAULT_LOCK = threading.Lock()


def current_environment() -> Environment:
    return Environment(os.environ.get("IRIS_ENV", "dev"))


def has_policy_loaded(engine: CedarEngine, passport: AgentPassport) -> bool:
    return bool(engine._policy_cache.get(passport.agent_id))


def load_passport_policy(engine: CedarEngine, passport: AgentPassport) -> None:
    if not passport.policy_ref:
        return
    policy_path = Path(passport.policy_ref)
    if not policy_path.is_absolute():
        policy_path = Path.cwd() / policy_path
    if policy_path.exists():
        engine.load_policy_file(passport.agent_id, policy_path)


def apply_no_policy_gate(
    engine: CedarEngine,
    passport: AgentPassport,
    env: Environment,
    result: PolicyResult,
) -> PolicyResult:
    """Fail open in dev/test when no policy is loaded; fail closed in staging/prod."""
    if has_policy_loaded(engine, passport):
        return result
    if env in (Environment.DEV, Environment.TEST):
        if result.decision == "DENY":
            return PolicyResult(
                decision="PERMIT_WITH_WARNINGS",
                violations=result.violations,
                agent_id=result.agent_id,
                action=result.action,
                resource=result.resource,
                environment=result.environment,
            )
    return result


def merge_prompt_violations(result: PolicyResult, prompt_violations: List[Violation]) -> PolicyResult:
    if not prompt_violations:
        return result
    from iris_core.models.policy import Severity

    violations = list(result.violations) + list(prompt_violations)
    critical = [v for v in violations if v.severity == Severity.CRITICAL]
    if critical:
        decision = "DENY"
    elif violations and result.decision == "PERMIT":
        env = Environment(result.environment) if result.environment else Environment.DEV
        if env in (Environment.DEV, Environment.TEST):
            decision = "PERMIT_WITH_WARNINGS"
        else:
            high = [v for v in violations if v.severity in (Severity.HIGH, Severity.CRITICAL)]
            decision = "DENY" if high else "PERMIT_WITH_WARNINGS"
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


def evaluate_api_call(
    engine: CedarEngine,
    vault: EvidenceVault,
    passport: AgentPassport,
    env: Environment,
    *,
    data_classification: Optional[str] = None,
    prompt_violations: Optional[List[Violation]] = None,
    additional: Optional[dict] = None,
    dlp_prompt_findings: Optional[list] = None,
    user_email: Optional[str] = None,
    user_role: Optional[str] = None,
    user_context: Optional[UserContext] = None,
) -> PolicyResult:
    effective_user = user_context or UserContext.from_params(
        user_email=user_email, user_role=user_role
    )
    user_fields = effective_user.evaluation_fields()
    ctx = EvaluationContext(
        agent_id=passport.agent_id,
        action="call",
        resource="anthropic-api",
        resource_type="api",
        environment=env,
        data_classification=data_classification or passport.data_classification.value,
        dlp_prompt_findings=dlp_prompt_findings,
        additional=additional or {},
        user_context=user_context,
        **user_fields,
    )
    result = engine.evaluate(passport, ctx)
    result = apply_no_policy_gate(engine, passport, env, result)
    result = merge_prompt_violations(result, prompt_violations or [])
    with _VAULT_LOCK:
        vault.record(ctx, result, passport=passport)
    return result


def enforce_result(result: PolicyResult, env: Environment) -> None:
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
            msg = (
                f"[IRIS WARNING] {violation.message} "
                f"Remediation: {violation.remediation}"
            )
            logger.warning(msg)
            print(msg, file=sys.stderr)
