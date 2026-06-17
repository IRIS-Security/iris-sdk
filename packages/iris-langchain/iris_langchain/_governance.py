"""Shared IRIS evaluation helpers for LangChain integrations."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from iris_core.hitl.handler import enforce_policy_result, finalize_evaluation
from iris_core.engine.cedar import CedarEngine, EvaluationContext
from iris_core.rbac.context import UserContext
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment
from iris_core.models.policy import PolicyResult, Severity, Violation

logger = logging.getLogger("iris.langchain")

_VAULT_LOCK = threading.Lock()

_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
_DOB = re.compile(
    r"\b(?:0[1-9]|1[0-2])[/-](?:0[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b"
)
_CROSS_REGION = re.compile(r"cn-north|china|beijing", re.IGNORECASE)
_HIGH_RISK_DOMAIN = re.compile(r"\b(loan|diagnosis|hiring)\b", re.IGNORECASE)


@dataclass
class RunSession:
    """Per-agent-run compliance tracking for Evidence Vault correlation."""

    run_id: str
    tool_calls: int = 0
    violations: int = 0
    permits: int = 0
    warnings: int = 0
    pii_output_violations: int = 0
    finalized: bool = False
    events: List[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.tool_calls == 0:
            return 1.0
        blocked = self.violations + self.pii_output_violations
        return max(0.0, (self.tool_calls - blocked) / self.tool_calls)

    def to_summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "total_tool_calls": self.tool_calls,
            "violations": self.violations,
            "pii_output_violations": self.pii_output_violations,
            "permits": self.permits,
            "warnings": self.warnings,
            "pass_rate": round(self.pass_rate, 4),
        }


def resolve_environment(env: Optional[Environment] = None) -> Environment:
    if env is not None:
        return env
    return Environment(os.environ.get("IRIS_ENV", "dev"))


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


def extract_regions(inputs: Optional[Dict[str, Any]]) -> tuple[Optional[str], Optional[str]]:
    if not inputs:
        return None, None
    data_region = inputs.get("data_region")
    destination_region = inputs.get("destination_region") or inputs.get("dest_region")
    return (
        str(data_region) if data_region is not None else None,
        str(destination_region) if destination_region is not None else None,
    )


def detect_pii(text: str) -> bool:
    if not text:
        return False
    return bool(_SSN.search(text) or _CREDIT_CARD.search(text) or _DOB.search(text))


def pii_output_violation(passport: AgentPassport, tool_name: str) -> Violation:
    return Violation(
        rule_id="IRIS-DATA-001",
        severity=Severity.HIGH,
        message=(
            f"Tool '{tool_name}' output for agent '{passport.name}' may contain PII "
            f"(SSN, payment card, or date-of-birth pattern)."
        ),
        compliance_refs=[
            "colorado-ai-act:impact-assessment",
            "gdpr:data-minimization",
        ],
        remediation=(
            "Redact sensitive data from tool outputs or restrict tools that return PII "
            "in production environments."
        ),
    )


def check_prompt_guardrails(prompt: str, passport: AgentPassport) -> List[Violation]:
    """Scan LLM prompts for cross-region and high-risk domain indicators."""
    if not prompt:
        return []

    violations: List[Violation] = []

    if detect_pii(prompt):
        violations.append(
            Violation(
                rule_id="IRIS-DATA-001",
                severity=Severity.HIGH,
                message=(
                    f"Prompt for agent '{passport.name}' may contain PII "
                    f"(SSN, payment card, or date-of-birth pattern)."
                ),
                compliance_refs=[
                    "colorado-ai-act:impact-assessment",
                    "gdpr:data-minimization",
                ],
                remediation=(
                    "Remove sensitive identifiers from the prompt or update the agent "
                    "passport data_classification to match the data being processed."
                ),
            )
        )

    if _CROSS_REGION.search(prompt):
        violations.append(
            Violation(
                rule_id="IRIS-XR-001",
                severity=Severity.CRITICAL,
                message=(
                    f"Prompt for agent '{passport.name}' references restricted "
                    f"cross-region geography (China / cn-north)."
                ),
                compliance_refs=["china-pipl:cross-border-transfer"],
                remediation=(
                    "Remove cross-region references from the prompt or document an "
                    "approved exception with your security engineer."
                ),
            )
        )

    if _HIGH_RISK_DOMAIN.search(prompt):
        violations.append(
            Violation(
                rule_id="CO-004",
                severity=Severity.HIGH,
                message=(
                    f"Prompt for agent '{passport.name}' references a high-risk "
                    f"consequential domain (loan, diagnosis, or hiring)."
                ),
                compliance_refs=["colorado-ai-act:sb-24-205:consumer-opt-out"],
                remediation=(
                    "Set user_consent_logged=True in policy context for consequential "
                    f"actions, or run 'iris compliance assess --agent {passport.agent_id}'."
                ),
            )
        )

    return violations


def merge_guardrail_violations(
    base: PolicyResult,
    extra_violations: List[Violation],
) -> PolicyResult:
    if not extra_violations:
        return base

    violations = list(base.violations) + list(extra_violations)
    critical = [v for v in violations if v.severity == Severity.CRITICAL]
    if critical or base.decision == "DENY":
        decision = "DENY" if critical else base.decision
    elif violations and base.decision == "PERMIT":
        decision = "PERMIT_WITH_WARNINGS"
    else:
        decision = base.decision

    return PolicyResult(
        decision=decision,
        violations=violations,
        agent_id=base.agent_id,
        action=base.action,
        resource=base.resource,
        environment=base.environment,
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
    run_id: Optional[str] = None,
    extra_violations: Optional[List[Violation]] = None,
    dlp_prompt_findings: Optional[list] = None,
    user_email: Optional[str] = None,
    user_role: Optional[str] = None,
) -> PolicyResult:
    user_ctx = UserContext.from_params(user_email, user_role)
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
        dlp_prompt_findings=dlp_prompt_findings,
        additional={"run_id": run_id} if run_id else {},
        **user_ctx.evaluation_fields(),
    )
    result = engine.evaluate(passport, ctx)
    result = apply_no_policy_gate(engine, passport, env, result)
    result = merge_guardrail_violations(result, extra_violations or [])
    with _VAULT_LOCK:
        finalize_evaluation(
            passport,
            ctx,
            result,
            vault,
            tool_name=resource,
            action=action,
        )
    return result


def record_audit_event(
    vault: EvidenceVault,
    *,
    run_id: str,
    event_type: str,
    resource: str,
    details: Optional[Dict[str, Any]] = None,
    violations: Optional[List[Violation]] = None,
    decision: str = "AUDIT",
) -> str:
    """Record a non-evaluation audit event tagged with the agent run_id."""
    event_id = str(uuid.uuid4())
    entry = {
        "event_id": event_id,
        "timestamp": datetime.utcnow().isoformat(),
        "agent_id": vault._agent_id,
        "run_id": run_id,
        "event_type": event_type,
        "action": event_type,
        "resource": resource,
        "decision": decision,
        "details": details or {},
        "violations": [
            {
                "rule_id": v.rule_id,
                "severity": v.severity.value,
                "message": v.message,
                "compliance_refs": v.compliance_refs,
            }
            for v in (violations or [])
        ],
    }
    with _VAULT_LOCK:
        with open(vault._log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    return event_id


def track_result(session: Optional[RunSession], result: PolicyResult) -> None:
    if session is None:
        return
    if result.decision == "PERMIT":
        session.permits += 1
    elif result.decision == "PERMIT_WITH_WARNINGS":
        session.warnings += 1
        session.violations += len(result.violations)
    elif result.decision == "DENY":
        session.violations += max(len(result.violations), 1)


def enforce_result(result: PolicyResult, env: Environment) -> None:
    enforce_policy_result(result, env)
