"""Shared IRIS evaluation helpers for CrewAI integrations."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from iris_core.dlp import DLPScanner
from iris_core.dlp.enforcement import enforce_prompt_dlp
from iris_core.engine.cedar import CedarEngine, EvaluationContext
from iris_core.rbac.context import UserContext
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment
from iris_core.models.policy import PolicyResult

from iris import IrisViolationError

logger = logging.getLogger("iris.crewai")

_VAULT_LOCK = threading.Lock()
_MOCK_SAFE_RESPONSE = "[IRIS] Action blocked by policy — mock safe response returned."


@dataclass
class EvaluationRecord:
    agent_name: str
    action: str
    resource: str
    decision: str
    violations: List[dict] = field(default_factory=list)


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


def parse_tool_input(tool_input: str) -> Optional[Dict[str, Any]]:
    """Parse CrewAI tool_input string into a dict when possible."""
    if not tool_input:
        return None
    stripped = tool_input.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"input": stripped}


def vault_partition_id(passport: AgentPassport) -> str:
    """Evidence vault partition key — one vault per agent name."""
    return passport.name or passport.agent_id


class AgentGovernor:
    """Per-agent Cedar evaluation, evidence recording, and compliance tracking."""

    def __init__(
        self,
        passport: AgentPassport,
        environment: Optional[Environment] = None,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
    ):
        self.passport = passport
        self.env = resolve_environment(environment)
        self._user_email = user_email
        self._user_role = user_role
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=vault_partition_id(passport))
        self._dlp = DLPScanner(passport)
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
        prompt_text = ""
        if inputs:
            prompt_text = str(
                inputs.get("input")
                or inputs.get("prompt")
                or inputs.get("tool_input")
                or ""
            )
        dlp_result = (
            enforce_prompt_dlp(
                self._dlp,
                self._vault,
                self.passport,
                self.env,
                prompt_text,
                resource=resource,
            )
            if prompt_text.strip()
            else None
        )
        user_ctx = UserContext.from_params(self._user_email, self._user_role)
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
            dlp_prompt_findings=dlp_result.findings if dlp_result else None,
            **user_ctx.evaluation_fields(),
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

    def evaluate_step_action(self, agent_action: Any) -> Optional[str]:
        """
        Evaluate a CrewAI AgentAction step without altering crew output formatting.

        Returns a mock safe response in dev when denied; raises in production.
        """
        from crewai.agents.parser import AgentAction, AgentFinish

        if isinstance(agent_action, AgentFinish):
            logger.debug(
                "IRIS step: agent=%s finished",
                vault_partition_id(self.passport),
            )
            return None

        if not isinstance(agent_action, AgentAction):
            return None

        tool_name = agent_action.tool
        inputs = parse_tool_input(agent_action.tool_input)
        result = self.evaluate_tool(action="call", resource=tool_name, inputs=inputs)

        if result.decision == "DENY":
            if self.env in (Environment.DEV, Environment.TEST):
                for violation in result.violations:
                    msg = (
                        f"[IRIS WARNING] {violation.message} "
                        f"Remediation: {violation.remediation}"
                    )
                    logger.warning(msg)
                    print(msg, file=sys.stderr)
                return _MOCK_SAFE_RESPONSE
            raise IrisViolationError(result)

        if result.decision == "PERMIT_WITH_WARNINGS":
            for violation in result.violations:
                msg = (
                    f"[IRIS WARNING] {violation.message} "
                    f"Remediation: {violation.remediation}"
                )
                logger.warning(msg)
                print(msg, file=sys.stderr)

        logger.debug(
            "IRIS step: agent=%s tool=%s decision=%s",
            vault_partition_id(self.passport),
            tool_name,
            result.decision,
        )
        return None

    @property
    def vault(self) -> EvidenceVault:
        return self._vault


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


def make_step_callback(
    governor: AgentGovernor,
    user_callback: Optional[Callable[..., Any]] = None,
) -> Callable[[Any], Any]:
    """Chain IRIS step evaluation with an optional user step_callback."""

    def iris_step_callback(step_output: Any) -> Any:
        mock_response = governor.evaluate_step_action(step_output)
        if user_callback is not None:
            user_result = user_callback(step_output)
            return user_result if user_result is not None else mock_response
        return mock_response

    return iris_step_callback


def _agent_pass_rate(records: List[EvaluationRecord]) -> float:
    if not records:
        return 1.0
    violations = sum(
        len(r.violations) if r.violations else (1 if r.decision == "DENY" else 0)
        for r in records
        if r.decision != "PERMIT"
    )
    return max(0.0, (len(records) - violations) / len(records))


def _agent_violation_count(records: List[EvaluationRecord]) -> int:
    return sum(
        len(r.violations) if r.violations else (1 if r.decision == "DENY" else 0)
        for r in records
        if r.decision != "PERMIT"
    )


def _violations_by_severity(records: List[EvaluationRecord]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        if record.decision == "PERMIT":
            continue
        if record.violations:
            for v in record.violations:
                counter[v["severity"]] += 1
        elif record.decision == "DENY":
            counter["unknown"] += 1
    return dict(counter)


def _most_violated_rule(records: List[EvaluationRecord]) -> Optional[str]:
    counter: Counter[str] = Counter()
    for record in records:
        if record.decision == "PERMIT":
            continue
        for v in record.violations:
            counter[v["rule_id"]] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def build_compliance_report(governors: Dict[str, AgentGovernor]) -> dict:
    """Aggregate per-agent evaluations into a crew compliance report."""
    agents_report: Dict[str, dict] = {}
    total_evaluations = 0
    total_crew_violations = 0
    violations_by_agent: Counter[str] = Counter()

    for role, governor in governors.items():
        records = governor.records
        agent_name = vault_partition_id(governor.passport)
        agent_violations = _agent_violation_count(records)
        total_evaluations += len(records)
        total_crew_violations += agent_violations
        violations_by_agent[agent_name] = agent_violations

        agents_report[role] = {
            "agent_name": agent_name,
            "total_evaluations": len(records),
            "total_violations": agent_violations,
            "violations_by_severity": _violations_by_severity(records),
            "most_violated_rule": _most_violated_rule(records),
            "pass_rate": round(_agent_pass_rate(records), 4),
        }

    crew_pass_rate = (
        round(max(0.0, (total_evaluations - total_crew_violations) / total_evaluations), 4)
        if total_evaluations
        else 1.0
    )
    most_problematic_agent = (
        violations_by_agent.most_common(1)[0][0] if violations_by_agent else None
    )

    all_severity: Counter[str] = Counter()
    all_rules: Counter[str] = Counter()
    for role, governor in governors.items():
        for severity, count in _violations_by_severity(governor.records).items():
            all_severity[severity] += count
        rule = _most_violated_rule(governor.records)
        if rule:
            all_rules[rule] += _agent_violation_count(governor.records)

    return {
        "agents": agents_report,
        "most_problematic_agent": most_problematic_agent,
        "total_crew_violations": total_crew_violations,
        "crew_pass_rate": crew_pass_rate,
        "total_evaluations": total_evaluations,
        "violations_by_severity": dict(all_severity),
        "most_common_rule_violations": [
            {"rule_id": rule_id, "count": count}
            for rule_id, count in all_rules.most_common(10)
        ],
    }
