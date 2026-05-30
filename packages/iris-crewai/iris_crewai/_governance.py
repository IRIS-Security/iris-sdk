"""Shared IRIS evaluation helpers for CrewAI integrations."""

from __future__ import annotations

import logging
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from iris_core.engine.cedar import CedarEngine, EvaluationContext
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment
from iris_core.models.policy import PolicyResult, Severity

from iris import IrisViolationError

logger = logging.getLogger("iris.crewai")

_VAULT_LOCK = threading.Lock()


@dataclass
class EvaluationRecord:
    agent_name: str
    action: str
    resource: str
    decision: str
    violations: List[dict] = field(default_factory=list)


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


def vault_partition_id(passport: AgentPassport) -> str:
    """Evidence vault partition key — one vault per agent name."""
    return passport.name or passport.agent_id


class AgentGovernor:
    """Per-agent Cedar evaluation, evidence recording, and compliance tracking."""

    def __init__(self, passport: AgentPassport, environment: Optional[Environment] = None):
        import os

        self.passport = passport
        self.env = environment or Environment(os.environ.get("IRIS_ENV", "dev"))
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=vault_partition_id(passport))
        load_passport_policy(self._engine, passport)
        self.records: List[EvaluationRecord] = []

    def evaluate_tool(
        self,
        *,
        action: str,
        resource: str,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> PolicyResult:
        data_region, destination_region = extract_regions(inputs)
        data_classification = None
        if inputs and inputs.get("data_classification") is not None:
            data_classification = str(inputs["data_classification"])
        ctx = EvaluationContext(
            agent_id=self.passport.agent_id,
            action=action,
            resource=resource,
            resource_type="tool",
            environment=self.env,
            data_region=data_region,
            destination_region=destination_region,
            data_classification=data_classification,
            user_consent_logged=bool(inputs.get("user_consent_logged")) if inputs else False,
        )
        result = self._engine.evaluate(self.passport, ctx)
        result = apply_no_policy_gate(self._engine, self.passport, self.env, result)
        with _VAULT_LOCK:
            self._vault.record(ctx, result)
        self._track(result)
        return result

    def _track(self, result: PolicyResult) -> None:
        self.records.append(
            EvaluationRecord(
                agent_name=vault_partition_id(self.passport),
                action=result.action,
                resource=result.resource,
                decision=result.decision,
                violations=[
                    {
                        "rule_id": v.rule_id,
                        "severity": v.severity.value,
                        "message": v.message,
                    }
                    for v in result.violations
                ],
            )
        )

    def record_step(self, step_output: Any) -> None:
        """Record crew step metadata without altering crew output formatting."""
        from crewai.agents.parser import AgentAction, AgentFinish

        if isinstance(step_output, AgentAction):
            logger.debug(
                "IRIS step: agent=%s tool=%s decision logged",
                vault_partition_id(self.passport),
                step_output.tool,
            )
        elif isinstance(step_output, AgentFinish):
            logger.debug(
                "IRIS step: agent=%s finished",
                vault_partition_id(self.passport),
            )

    @property
    def vault(self) -> EvidenceVault:
        return self._vault


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


def make_step_callback(
    governor: AgentGovernor,
    user_callback: Optional[Callable[..., Any]] = None,
) -> Callable[[Any], Any]:
    """Chain IRIS step recording with an optional user step_callback."""

    def iris_step_callback(step_output: Any) -> Any:
        governor.record_step(step_output)
        if user_callback is not None:
            return user_callback(step_output)
        return None

    return iris_step_callback


def build_compliance_report(governors: Dict[str, AgentGovernor]) -> dict:
    """Aggregate per-agent evaluations into a crew compliance report."""
    all_records: List[EvaluationRecord] = []
    for governor in governors.values():
        all_records.extend(governor.records)

    violation_records = [
        r for r in all_records if r.decision in ("DENY", "PERMIT_WITH_WARNINGS")
    ]
    violations_by_agent: Dict[str, int] = Counter()
    violations_by_severity: Counter = Counter()
    rule_counter: Counter = Counter()

    for record in violation_records:
        violations_by_agent[record.agent_name] += len(record.violations) or 1
        for v in record.violations:
            violations_by_severity[v["severity"]] += 1
            rule_counter[v["rule_id"]] += 1

    total_violations = sum(
        len(r.violations) if r.violations else 1
        for r in violation_records
    )

    return {
        "total_evaluations": len(all_records),
        "total_violations": total_violations,
        "violations_by_agent": dict(violations_by_agent),
        "violations_by_severity": dict(violations_by_severity),
        "most_common_rule_violations": [
            {"rule_id": rule_id, "count": count}
            for rule_id, count in rule_counter.most_common(10)
        ],
        "agents": {
            role: {
                "evaluations": len(governor.records),
                "violations": sum(
                    len(r.violations) if r.violations else (1 if r.decision == "DENY" else 0)
                    for r in governor.records
                    if r.decision != "PERMIT"
                ),
                "permits": sum(1 for r in governor.records if r.decision == "PERMIT"),
                "evidence_events": len(governor.vault.get_events()),
            }
            for role, governor in governors.items()
        },
    }
