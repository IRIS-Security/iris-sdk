"""
IRIS Python SDK — AI Agent Governance, fully local.

The primary entry point for Python developers building AI agents.
Zero cloud infrastructure required. Cedar evaluation runs in-process.

Quickstart:
    from iris import IrisAgent, iris_guard

    agent = IrisAgent(
        name="my-agent",
        owner="platform-team",
        compliance=["colorado-ai-act"]
    )

    @iris_guard(agent)
    def call_payments_api(user_id: str) -> dict:
        # IRIS intercepts this call and evaluates it against policy
        ...
"""

from __future__ import annotations
from typing import Optional, List, Callable, Any
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta
import os
import sys

# ── Re-export the full public API ──────────────────────────────────────────────
from iris_core.models.passport import (
    AgentPassport,
    DataClassification,
    Environment,
    ComplianceTag,
    ToolPermission,
    UserContext,
)
from iris_core.hitl.models import HITLConfig, HITLConditionRule, HITLStatus
from iris_core.hitl.error import IrisHITLRequiredError
from iris.hitl import HITLPoller
from iris_core.models.policy import PolicyResult, Violation, Severity
from iris_core.engine.cedar import CedarEngine, EvaluationContext
from iris_core.engine.compiler import PolicyCompiler, CompilationResult
from iris_core.compliance.registry import ComplianceRegistry
from iris_core.evidence.vault import EvidenceVault
from iris_core.cost.tracker import CostSummary, CostTracker, CostEntry
from iris_core.cost.pricing import PricingRegistry

__version__ = "0.2.2"
__all__ = [
    # Main classes
    "IrisAgent",
    "iris_guard",
    "iris_scan",
    # Models
    "AgentPassport",
    "DataClassification",
    "Environment",
    "ComplianceTag",
    "ToolPermission",
    "UserContext",
    "EvaluationContext",
    "PolicyResult",
    "Violation",
    "Severity",
    # Engines
    "CedarEngine",
    "PolicyCompiler",
    "CompilationResult",
    "ComplianceRegistry",
    "EvidenceVault",
    "CostTracker",
    "CostSummary",
    "CostEntry",
    "PricingRegistry",
    "IrisViolationError",
    "IrisCrisisDetectedError",
    "IrisHITLRequiredError",
    "HITLConfig",
    "HITLConditionRule",
    "HITLStatus",
    "HITLPoller",
]


class IrisAgent:
    """
    The primary IRIS SDK entry point for Python developers.

    Think of IrisAgent as the agent's passport officer. You declare who
    the agent is and what it is allowed to do. IRIS handles the rest:
    policy compilation, runtime evaluation, and compliance reporting.

    Example:
        agent = IrisAgent(
            name="support-agent",
            owner="platform-team@company.com",
            team="platform",
            data_classification=DataClassification.PII,
            compliance=["colorado-ai-act", "soc2"],
            is_high_risk_ai=True,        # triggers Colorado AI Act checks
        )

        # Generate policy from natural language intent
        result = agent.compile_policy(
            intent="This agent can read support tickets and respond to customers. "
                   "It must never access payment data or write to any external system."
        )

        # Use as a decorator on any function that calls an AI tool
        @agent.guard(tool="zendesk-api", action="read")
        def fetch_ticket(ticket_id: str) -> dict:
            ...
    """

    def __init__(
        self,
        name: str,
        owner: str,
        team: str = "",
        data_classification: DataClassification = DataClassification.INTERNAL,
        compliance: Optional[List[str]] = None,
        environments: Optional[List[str]] = None,
        is_high_risk_ai: bool = False,
        policy_dir: Optional[Path] = None,
        telemetry: bool = False,          # opt-in only, never default True
        environment: Optional[str] = None,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        user_context: Optional[UserContext] = None,
    ):
        compliance_tags = [ComplianceTag(c) for c in (compliance or [])]
        envs = [Environment(e) for e in (environments or ["dev", "test", "staging", "production"])]
        current_env = Environment(environment or os.environ.get("IRIS_ENV", "dev"))
        self._user_ctx = user_context or UserContext.from_params(
            user_email=user_email, user_role=user_role
        )
        self._default_user_context = user_context

        self.passport = AgentPassport(
            name=name,
            owner=owner,
            team=team,
            data_classification=data_classification,
            compliance_tags=compliance_tags,
            environments=envs,
            is_high_risk_ai=is_high_risk_ai,
        )

        self._current_env = current_env
        self._policy_dir = policy_dir or Path.cwd() / "governance" / "agents" / name
        self._engine = CedarEngine(policy_dir=self._policy_dir)
        self._compiler: Optional[PolicyCompiler] = None
        self._vault = EvidenceVault(agent_id=self.passport.agent_id)
        self._cost_tracker = CostTracker(
            agent_id=self.passport.agent_id,
            agent_name=self.passport.name,
        )
        self._telemetry = telemetry

        # Load policy if it exists on disk
        policy_file = self._policy_dir / "policy.cedar"
        if policy_file.exists():
            self._engine.load_policy_file(self.passport.agent_id, policy_file)

    def _get_compiler(self) -> PolicyCompiler:
        if self._compiler is None:
            self._compiler = PolicyCompiler()
        return self._compiler

    def compile_policy(
        self,
        intent: str,
        write_to_disk: bool = True,
    ) -> CompilationResult:
        """
        Compile natural language intent to Cedar policy.

        The developer writes what they want. IRIS writes the Cedar.

        Args:
            intent: Plain English description of agent permissions.
            write_to_disk: If True, writes policy.cedar and policy-intent.md
                           to the governance GitOps directory.
        """
        result = self._get_compiler().compile(intent, self.passport)

        if write_to_disk and result.success:
            self._policy_dir.mkdir(parents=True, exist_ok=True)
            (self._policy_dir / "policy.cedar").write_text(result.cedar_policy)
            (self._policy_dir / "policy-intent.md").write_text(result.intent_markdown)
            (self._policy_dir / "passport.yaml").write_text(self.passport.to_yaml())
            self._engine.load_policy(self.passport.agent_id, result.cedar_policy)
            print(f"[IRIS] Policy compiled and written to {self._policy_dir}")

        return result

    def guard(
        self,
        tool: str,
        action: str = "call",
        data_region: Optional[str] = None,
        destination_region: Optional[str] = None,
        data_classification: Optional[str] = None,
        user_context: Optional[UserContext] = None,
    ) -> Callable:
        """
        Decorator that intercepts function calls and evaluates them against policy.

        This is the sidecar in decorator form. Use it on any function that
        calls an external tool, API, or data source.

        Example:
            @agent.guard(tool="payments-api", action="read")
            def get_payment_status(order_id: str) -> dict:
                return payments_client.get(order_id)
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                effective_user = user_context or self._default_user_context
                user_fields = self._user_ctx.evaluation_fields()
                if effective_user:
                    user_fields = effective_user.evaluation_fields()
                ctx = EvaluationContext(
                    agent_id=self.passport.agent_id,
                    action=action,
                    resource=tool,
                    resource_type="tool",
                    environment=self._current_env,
                    data_region=data_region,
                    destination_region=destination_region,
                    data_classification=data_classification,
                    user_context=effective_user,
                    **user_fields,
                )
                result = self.evaluate(ctx)

                if result.decision == "DENY":
                    raise IrisViolationError(result)
                elif result.decision == "PERMIT_WITH_WARNINGS":
                    for v in result.violations:
                        print(f"[IRIS WARNING] {v.message}", file=sys.stderr)

                return func(*args, **kwargs)
            return wrapper
        return decorator

    def evaluate(self, context: EvaluationContext) -> PolicyResult:
        """Direct policy evaluation without the decorator pattern."""
        result = self._engine.evaluate(self.passport, context)
        self._vault.record(context, result, passport=self.passport)
        from iris._telemetry import maybe_fire_first_policy_run

        maybe_fire_first_policy_run()
        return result

    def check_compliance(
        self,
        framework: Optional[str] = None,
    ) -> List[Violation]:
        """
        Run a compliance check against the agent's passport and policy.
        Equivalent to 'iris compliance check' from the CLI.
        """
        registry = ComplianceRegistry()
        return registry.check_passport(
            self.passport,
            framework or [t.value for t in self.passport.compliance_tags],
        )

    @property
    def total_cost_usd(self) -> float:
        """Total LLM spend for this agent since install."""
        summary = self._cost_tracker.get_summary()
        return summary.total_cost_usd

    def cost_report(self, days: int = 30) -> CostSummary:
        """Return a cost summary for the last N days."""
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return self._cost_tracker.get_summary(since=since)

    @property
    def is_ready_for_production(self) -> bool:
        """Quick check: is this agent compliant enough for production?"""
        violations = self.check_compliance()
        critical = [v for v in violations if v.severity == Severity.CRITICAL]
        return len(critical) == 0


class IrisViolationError(Exception):
    """
    Raised when an agent action is blocked by IRIS policy.

    The structured error is returned to the calling agent with a plain-English
    explanation of what was blocked and how to remediate.
    """

    def __init__(self, result: PolicyResult, is_compliance_block: bool = False):
        self.result = result
        self.is_compliance_block = is_compliance_block or getattr(
            result, "is_compliance_block", False
        )
        primary = result.violations[0] if result.violations else None
        message = (
            f"\n[IRIS POLICY VIOLATION]\n"
            f"Decision: {result.decision}\n"
            f"Agent: {result.agent_id}\n"
            f"Action: {result.action} on {result.resource}\n"
            f"Environment: {result.environment}\n"
        )
        if primary:
            message += (
                f"\nViolation: {primary.message}\n"
                f"Rule: {primary.rule_id}\n"
                f"Compliance: {', '.join(primary.compliance_refs)}\n"
                f"Remediation: {primary.remediation}\n"
            )
        super().__init__(message)


class IrisCrisisDetectedError(Exception):
    """
    Raised when crisis language is detected in user input (CHAT-004).

    This is NOT a policy violation — applications catch this error and
    display crisis resources to the user.
    """

    def __init__(self, crisis_response):
        from iris_core.dlp.types import CrisisResponse

        self.crisis_response: CrisisResponse = crisis_response
        message = (
            f"\n[IRIS CRISIS DETECTED — CHAT-004]\n"
            f"{crisis_response.message}\n\n"
            f"Crisis resources (display to user):\n"
            + "\n".join(f"  • {r}" for r in crisis_response.resources)
            + f"\n\nAction required: {crisis_response.action_required}\n"
        )
        super().__init__(message)


def iris_scan(
    directory: Optional[Path] = None,
    framework: Optional[str] = None,
) -> List[Violation]:
    """
    Scan a directory for agent passports and check compliance.
    Equivalent to 'iris scan' from the CLI.

    This is the traction metric for investors: every developer who runs
    iris_scan() or 'iris scan' is a weekly active user.
    """
    scan_dir = directory or Path.cwd() / "governance"
    registry = ComplianceRegistry()
    violations = []

    for passport_file in scan_dir.rglob("passport.yaml"):
        try:
            passport = AgentPassport.from_yaml(passport_file.read_text())
            agent_violations = registry.check_passport(passport, framework)
            violations.extend(agent_violations)
            status = "PASS" if not agent_violations else f"FAIL ({len(agent_violations)} violations)"
            print(f"[IRIS SCAN] {passport.name}: {status}")
        except Exception as e:
            print(f"[IRIS SCAN] Could not parse {passport_file}: {e}", file=sys.stderr)

    return violations
