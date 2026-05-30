"""Shared IRIS evaluation helpers for LangChain integrations."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from iris_core.engine.cedar import CedarEngine, EvaluationContext
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment
from iris_core.models.policy import PolicyResult

from iris import IrisViolationError

logger = logging.getLogger("iris.langchain")

_VAULT_LOCK = threading.Lock()


def has_policy_loaded(engine: CedarEngine, passport: AgentPassport) -> bool:
    return bool(engine._policy_cache.get(passport.agent_id))


def load_passport_policy(engine: CedarEngine, passport: AgentPassport) -> None:
    """Load Cedar policy from passport.policy_ref when present on disk."""
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
    """
    Fail open in dev/test when no policy is loaded; fail closed in staging/prod.
    """
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


def extract_regions(inputs: Optional[Dict[str, Any]]) -> tuple[Optional[str], Optional[str]]:
    if not inputs:
        return None, None
    data_region = inputs.get("data_region")
    destination_region = inputs.get("destination_region") or inputs.get("dest_region")
    return (
        str(data_region) if data_region is not None else None,
        str(destination_region) if destination_region is not None else None,
    )


def evaluate_and_record(
    engine: CedarEngine,
    vault: EvidenceVault,
    passport: AgentPassport,
    env: Environment,
    *,
    action: str,
    resource: str,
    resource_type: str = "tool",
    data_region: Optional[str] = None,
    destination_region: Optional[str] = None,
    data_classification: Optional[str] = None,
    user_consent_logged: bool = False,
) -> PolicyResult:
    ctx = EvaluationContext(
        agent_id=passport.agent_id,
        action=action,
        resource=resource,
        resource_type=resource_type,
        environment=env,
        data_region=data_region,
        destination_region=destination_region,
        data_classification=data_classification,
        user_consent_logged=user_consent_logged,
    )
    result = engine.evaluate(passport, ctx)
    result = apply_no_policy_gate(engine, passport, env, result)
    with _VAULT_LOCK:
        vault.record(ctx, result)
    return result


def enforce_result(result: PolicyResult) -> None:
    if result.decision == "DENY":
        raise IrisViolationError(result)
    if result.decision == "PERMIT_WITH_WARNINGS":
        for violation in result.violations:
            msg = (
                f"[IRIS WARNING] {violation.message} "
                f"Remediation: {violation.remediation}"
            )
            logger.warning(msg)
            print(msg, file=sys.stderr)
