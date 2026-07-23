"""
CedarEngine: local in-process Cedar policy evaluation.

This is the traffic cop at the toll booth. It runs entirely in-process
with no network calls required. Every agent action is evaluated against
the agent's Cedar policy in under 5ms.

Cedar is Amazon's open-source policy language, purpose-built for
fine-grained authorization. IRIS uses it as the policy runtime because:
  1. It is formally verified — policies have provable correctness
  2. It evaluates in microseconds
  3. It is human-auditable (security engineers can read Cedar)
  4. It maps cleanly to GitOps (Cedar files are text, diffs are readable)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from uuid import uuid4
import json
import re
import fnmatch
import logging

from iris_core.drift.detector import SessionIntentTracker
from iris_core.evidence.vault import EvidenceVault

from iris_core.models.policy import PolicyResult, Violation, Severity, Action
from iris_core.models.passport import AgentPassport, Environment, ComplianceTag, UserContext
from iris_core.models.context import EvaluationContext
from iris_core.dlp.types import DLPFinding
from iris_core.compliance.violation_response import ViolationResponse, get_effective_response
from iris_core.hitl.models import HITLConditionRule
from iris_core.org_policy.enforcement import EnforcementEngine, EnforcementLevel
from iris_core.org_policy.loader import OrgPolicyLoader
from iris_core.org_policy.models import ResolvedPolicy

logger = logging.getLogger("iris.cedar")

# Backwards-compatible re-export
__all__ = ["CedarEngine", "EvaluationContext"]


class CedarEngine:
    """
    Local Cedar policy evaluator.

    In Phase 1, this is a Python implementation of Cedar's evaluation
    semantics. In Phase 2, this will call the official Cedar Rust library
    via PyO3 bindings for full spec compliance and maximum performance.

    The API contract is stable — switching the backend from Python to
    Rust does not change any calling code.
    """

    def __init__(self, policy_dir: Optional[Path] = None, governance_root: Optional[Path] = None):
        self._policy_dir = policy_dir or Path.home() / ".iris" / "policies"
        self._governance_root = governance_root
        self._policy_cache: Dict[str, str] = {}
        self._compliance_bundles: Dict[str, str] = {}
        self._model_registry = None
        self._directive_registry = None
        self._org_policy_loader = OrgPolicyLoader(governance_root or Path.cwd())
        self._resolved_policy: Optional[ResolvedPolicy] = None
        self._enforcement_engine = EnforcementEngine()
        self._session_trackers: Dict[Tuple[str, str], SessionIntentTracker] = {}
        self._load_built_in_bundles()
        self._load_model_governance()

    def _load_resolved_policy(self) -> ResolvedPolicy:
        if self._resolved_policy is None:
            self._resolved_policy = self._org_policy_loader.load(self._governance_root)
        return self._resolved_policy

    def reload_org_policy(self) -> ResolvedPolicy:
        self._org_policy_loader._resolved = None
        self._resolved_policy = None
        return self._load_resolved_policy()

    @staticmethod
    def _apply_org_policy(passport: AgentPassport, policy: ResolvedPolicy) -> AgentPassport:
        """Inject org mandatory compliance tags into the effective passport."""
        mandatory = policy.org_baseline.mandatory_compliance_tags
        if not mandatory:
            return passport
        tag_values = {t.value for t in passport.compliance_tags}
        new_tags = list(passport.compliance_tags)
        for tag_str in mandatory:
            if tag_str not in tag_values:
                try:
                    new_tags.append(ComplianceTag(tag_str))
                    tag_values.add(tag_str)
                except ValueError:
                    logger.debug("Unknown mandatory compliance tag: %s", tag_str)
        if new_tags == passport.compliance_tags:
            return passport
        from dataclasses import replace

        return replace(passport, compliance_tags=new_tags)

    @staticmethod
    def _framework_active(
        framework: str,
        effective_frameworks: List[str],
        use_dynamic_frameworks: bool,
    ) -> bool:
        if not use_dynamic_frameworks:
            return True
        return framework in effective_frameworks

    def _load_model_governance(self) -> None:
        from iris_core.models.model_registry import ModelRegistry
        from iris_core.models.directives import DirectiveRegistry

        self._model_registry = ModelRegistry.load(self._governance_root)
        self._directive_registry = DirectiveRegistry.load(self._governance_root)

    def reload_model_governance(self) -> None:
        """Hot-reload model registry and directives (e.g. after a government directive)."""
        self._load_model_governance()

    def _load_built_in_bundles(self) -> None:
        """Load the IRIS compliance bundles that ship with the SDK."""
        bundles_dir = Path(__file__).parent.parent / "compliance" / "bundles"
        if bundles_dir.exists():
            for cedar_file in bundles_dir.glob("*.cedar"):
                self._compliance_bundles[cedar_file.stem] = cedar_file.read_text()

    def load_policy(self, agent_id: str, cedar_str: str) -> None:
        """Load a Cedar policy string for a specific agent."""
        self._policy_cache[agent_id] = cedar_str

    def load_policy_file(self, agent_id: str, policy_path: Path) -> None:
        """Load a Cedar policy from the GitOps repo on disk."""
        if not policy_path.exists():
            raise FileNotFoundError(
                f"Policy file not found: {policy_path}\n"
                f"Run 'iris policy generate --agent {agent_id}' to create one."
            )
        self._policy_cache[agent_id] = policy_path.read_text()

    def evaluate(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> PolicyResult:
        """
        Evaluate an agent action against its Cedar policy.

        This is the core toll booth decision. The result is always one of:
          - PERMIT: the action is allowed, proceed
          - DENY: the action is blocked, return structured error to agent
          - NOT_APPLICABLE: no policy covers this action (treated as DENY in prod)

        Target: under 5ms p99 for in-process evaluation.
        """
        cedar_policy = self._policy_cache.get(passport.agent_id)
        if not cedar_policy:
            return PolicyResult(
                decision="DENY",
                violations=[Violation(
                    rule_id="IRIS-001",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Agent '{passport.name}' has no policy loaded. "
                        f"Run 'iris policy generate --agent {passport.agent_id}' "
                        f"to generate a policy from your intent file."
                    ),
                    compliance_refs=["colorado-ai-act:transparency"],
                    remediation="Generate and commit a policy before deploying this agent.",
                )],
            )

        resolved_policy = self._load_resolved_policy()
        env_name = context.resolved_environment_name
        enforcement = resolved_policy.get_enforcement_level(env_name)
        effective_frameworks = resolved_policy.get_effective_frameworks(env_name)
        use_dynamic = not resolved_policy.is_default
        effective_passport = self._apply_org_policy(passport, resolved_policy)

        violations = []

        # ── Cross-region detection (Phase 1: pattern matching) ─────────────────
        cross_region_violation = self._check_cross_region(effective_passport, context)
        if cross_region_violation:
            violations.append(cross_region_violation)

        # ── Tool permission check ──────────────────────────────────────────────
        tool_violation = self._check_tool_permission(effective_passport, context)
        if tool_violation:
            violations.append(tool_violation)

        # ── Data classification check ─────────────────────────────────────────
        data_violation = self._check_data_classification(effective_passport, context)
        if data_violation:
            violations.append(data_violation)

        # ── Colorado AI Act checks ────────────────────────────────────────────
        if effective_passport.requires_colorado_compliance() and self._framework_active(
            "colorado-ai-act", effective_frameworks, use_dynamic
        ):
            co_violations = self._check_colorado_act(effective_passport, context)
            violations.extend(co_violations)

        # ── Colorado Mental Health AI (HB 26-1195) — absolute blocks always run ─
        if ComplianceTag.COLORADO_MENTAL_HEALTH_AI in effective_passport.compliance_tags:
            mh_violations = self._check_mental_health_ai(effective_passport, context)
            violations.extend(mh_violations)

        # ── Illinois AI Video Interview Act ─────────────────────────────────────
        if (
            ComplianceTag.ILLINOIS_AI_VIDEO in effective_passport.compliance_tags
            and self._framework_active("illinois-ai-video", effective_frameworks, use_dynamic)
        ):
            violations.extend(self._check_illinois_ai_video(effective_passport, context))

        # ── NYC Local Law 144 (AEDTs) ─────────────────────────────────────────
        if (
            ComplianceTag.NYC_LL144 in effective_passport.compliance_tags
            and self._framework_active("nyc-ll144", effective_frameworks, use_dynamic)
        ):
            violations.extend(self._check_nyc_ll144(effective_passport, context))

        # ── User RBAC (PRO tier) ─────────────────────────────────────────────
        rbac_violation = self._check_user_rbac(effective_passport, context)
        if rbac_violation:
            violations.append(rbac_violation)

        # ── Model governance (tier, export control, directives) ─────────────
        model_violations = self._check_model_governance(effective_passport, context)
        violations.extend(model_violations)

        # ── User delegation ───────────────────────────────────────────────────
        delegation_violations = self._check_delegation(effective_passport, context)
        violations.extend(delegation_violations)

        # ── Environment gate ──────────────────────────────────────────────────
        if not effective_passport.is_compliant_for_env(context.environment):
            violations.append(Violation(
                rule_id="IRIS-ENV-001",
                severity=Severity.CRITICAL,
                message=(
                    f"Agent '{passport.name}' is not approved for "
                    f"'{context.resolved_environment_name}' environment. "
                    f"Approved environments: {[e.value for e in passport.environments]}"
                ),
                compliance_refs=["iris:environment-gate"],
                remediation=(
                    "Update the agent passport to include this environment "
                    "and get security engineer approval."
                ),
            ))

        warn_only_violations: List[Violation] = []

        if violations:
            (
                violations,
                inform_violations,
                requires_hitl,
                hitl_rule,
                hitl_review_type,
                compliance_hitl_violation,
                is_compliance_block,
                warn_only_violations,
            ) = self._apply_violation_responses(
                effective_passport, violations, enforcement
            )

            if is_compliance_block:
                decision = "DENY"
            elif requires_hitl:
                decision = "PERMIT"
            elif warn_only_violations:
                decision = "PERMIT_WITH_WARNINGS"
            else:
                critical = [v for v in violations if v.severity == Severity.CRITICAL]
                if resolved_policy.is_default:
                    decision = (
                        "DENY" if critical else self._env_decision(context.environment, violations)
                    )
                elif enforcement == EnforcementLevel.ENFORCE:
                    decision = "DENY" if critical else "PERMIT_WITH_WARNINGS"
                else:
                    decision = "PERMIT_WITH_WARNINGS" if violations else "PERMIT"
        else:
            decision = "PERMIT"
            inform_violations = []
            warn_only_violations = []
            requires_hitl = False
            hitl_rule = ""
            hitl_review_type = "business"
            compliance_hitl_violation = None
            is_compliance_block = False

        cedar_annotations = self._match_cedar_annotations(cedar_policy, context)
        if not context.hitl_approved:
            business_hitl, business_reason = self._check_hitl_required(
                passport, context, cedar_annotations
            )
            if business_hitl and not is_compliance_block:
                requires_hitl = True
                hitl_rule = business_reason
                hitl_review_type = "business"

        session_id = (
            context.user_context.session_id
            if context.user_context and context.user_context.session_id
            else context.additional.get("session_id")
        ) or str(uuid4())
        tracker_key = (session_id, passport.agent_id)
        if tracker_key not in self._session_trackers:
            self._session_trackers[tracker_key] = SessionIntentTracker(
                session_id=session_id,
                agent_id=passport.agent_id,
                original_intent=passport.description or "",
            )
        action_label = (
            f"{context.action}/{context.resource}" if context.resource else context.action
        )
        drift_event = self._session_trackers[tracker_key].evaluate(action_label)

        if drift_event.flagged:
            try:
                vault = EvidenceVault(agent_id=passport.agent_id)
                vault.record_drift(drift_event)
            except Exception:
                pass  # drift tracking never blocks governance

            hitl_config = passport.hitl_config
            if (
                hitl_config
                and hitl_config.enabled
                and hitl_config.step_up_on_intent_drift
                and not requires_hitl
                and not is_compliance_block
                and not context.hitl_approved
            ):
                requires_hitl = True
                hitl_rule = (
                    f"Action outside declared intent — semantic drift "
                    f"{drift_event.semantic_distance:.2f} > {drift_event.drift_threshold} "
                    "(hitl_config.step_up_on_intent_drift)"
                )
                hitl_review_type = "business"

        # Cost budget check (Phase 6b) — same shape as the drift block above:
        # a numeric signal computed outside evaluate(), a threshold declared
        # on the passport, and a non-blocking evidence write before the
        # DENY/STEP_UP decision. Known limitation: the daily cumulative
        # check reads already-recorded history (record_llm_cost_async runs
        # in a detached background thread), so a burst of concurrent calls
        # could all read stale totals — best-effort, not airtight, inherent
        # to cost only being known post-call.
        budget_config = passport.budget_config
        cost_flagged = False
        if (
            budget_config
            and budget_config.enabled
            and not context.hitl_approved
            and not is_compliance_block
        ):
            from datetime import datetime, timezone

            from iris_core.cost.tracker import CostTracker

            estimated_cost = context.additional.get("estimated_call_cost_usd")
            overage_usd = 0.0
            overage_reason = ""

            if (
                budget_config.per_call_budget_usd is not None
                and estimated_cost is not None
                and estimated_cost > budget_config.per_call_budget_usd
            ):
                overage_usd = estimated_cost - budget_config.per_call_budget_usd
                overage_reason = (
                    f"Estimated call cost ${estimated_cost:.4f} exceeds per-call "
                    f"budget ${budget_config.per_call_budget_usd:.4f} "
                    "(passport.budget.per_call_budget_usd)"
                )
            elif budget_config.daily_budget_usd is not None:
                try:
                    today_start = datetime.now(timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ).isoformat()
                    cumulative_cost = CostTracker(
                        passport.agent_id, passport.name
                    ).get_summary(since=today_start).total_cost_usd
                except Exception:
                    cumulative_cost = None
                if cumulative_cost is not None and cumulative_cost > budget_config.daily_budget_usd:
                    overage_usd = cumulative_cost - budget_config.daily_budget_usd
                    overage_reason = (
                        f"Cumulative daily spend ${cumulative_cost:.4f} exceeds "
                        f"daily budget ${budget_config.daily_budget_usd:.4f} "
                        "(passport.budget.daily_budget_usd)"
                    )

            cost_flagged = overage_usd > 0
            try:
                vault = EvidenceVault(agent_id=passport.agent_id)
                vault.record_cost_governance(
                    within_budget=not cost_flagged,
                    decision=(budget_config.on_overage if cost_flagged else "within_budget"),
                    estimated_cost_usd=estimated_cost,
                    overage_usd=overage_usd,
                    reason=overage_reason,
                )
            except Exception:
                pass  # cost governance evidence never blocks the call

            if cost_flagged:
                if budget_config.on_overage == "deny":
                    decision = "DENY"
                    violations = violations + [
                        Violation(
                            rule_id="COST-BUDGET-001",
                            severity=Severity.HIGH,
                            message=overage_reason,
                            compliance_refs=[],
                            remediation="Increase the configured budget or reduce call size.",
                        )
                    ]
                elif not requires_hitl:
                    requires_hitl = True
                    hitl_rule = overage_reason
                    hitl_review_type = "business"

        # Trust state (Phase 7a) — observation-only: a rolling-window tally
        # of this agent's recent violations/HITL denials, surfaced on
        # PolicyResult and recorded to evidence, but never blocking or
        # forcing HITL by itself. Enforcement on trust state is a separate,
        # paid concern (quarantine-by-policy), not built here.
        trust_config = passport.trust_state_config
        trust_result = None
        if (
            trust_config
            and trust_config.enabled
            and not context.hitl_approved
            and not is_compliance_block
        ):
            from iris_core.trust.state import compute_trust_state

            try:
                trust_result = compute_trust_state(passport.agent_id, trust_config)
                vault = EvidenceVault(agent_id=passport.agent_id)
                vault.record_trust_state(
                    trust_state=trust_result.state.value,
                    reason=trust_result.reason,
                    violation_count=trust_result.violation_count,
                    hitl_denial_count=trust_result.hitl_denial_count,
                )
            except Exception:
                trust_result = None  # trust state is observation-only; never blocks the call

        return PolicyResult(
            decision=decision,
            violations=violations,
            agent_id=passport.agent_id,
            action=context.action,
            resource=context.resource,
            environment=context.resolved_environment_name,
            requires_hitl=requires_hitl and not context.hitl_approved,
            hitl_rule=hitl_rule,
            hitl_review_type=hitl_review_type,
            compliance_hitl_violation=compliance_hitl_violation,
            is_compliance_block=is_compliance_block,
            cedar_annotations=cedar_annotations,
            inform_violations=inform_violations,
            drift_score=drift_event.semantic_distance,
            drift_flagged=drift_event.flagged,
            aarm_r7=True,
            trust_state=trust_result.state.value if trust_result else None,
            trust_state_reason=trust_result.reason if trust_result else None,
        )

    def _env_decision(self, env: Environment, violations: List[Violation]) -> str:
        """
        Apply the four-environment inspection model.
        Dev and test: fail open (warn). Staging and prod: fail closed (deny).
        """
        if env in (Environment.DEV, Environment.TEST):
            return "PERMIT_WITH_WARNINGS"
        return "DENY"

    def _check_cross_region(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> Optional[Violation]:
        if not context.data_region or not context.destination_region:
            return None
        if context.data_region == context.destination_region:
            return None

        restricted_pairs = [
            ("cn-north-1", "us-east-1", "china-pipl:cross-border-transfer"),
            ("cn-northwest-1", "us-east-1", "china-pipl:cross-border-transfer"),
            ("cn-north-1", "us-west-2", "china-pipl:cross-border-transfer"),
            ("us-east-1", "cn-north-1", "china-pipl:cross-border-transfer"),
            ("us-east-1", "cn-northwest-1", "china-pipl:cross-border-transfer"),
            ("us-west-2", "cn-north-1", "china-pipl:cross-border-transfer"),
            ("us-west-2", "cn-northwest-1", "china-pipl:cross-border-transfer"),
            ("eu-west-1", "cn-north-1", "gdpr:chapter-5-transfer"),
            ("eu-central-1", "cn-north-1", "gdpr:chapter-5-transfer"),
        ]

        for src, dst, ref in restricted_pairs:
            if context.data_region == src and context.destination_region == dst:
                return Violation(
                    rule_id="IRIS-XR-001",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Cross-region data transfer blocked: "
                        f"{context.data_region} → {context.destination_region}. "
                        f"This transfer violates {ref}."
                    ),
                    compliance_refs=[ref],
                    remediation=(
                        "Review your data residency requirements. "
                        "If this transfer is required, contact your security engineer "
                        "to request a documented exception."
                    ),
                )
        return None

    def _check_tool_permission(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> Optional[Violation]:
        if context.resource_type != "tool":
            return None

        allowed_tool_ids = [t.tool_id for t in passport.tool_permissions]
        if context.resource not in allowed_tool_ids:
            return Violation(
                rule_id="IRIS-TOOL-001",
                severity=Severity.HIGH,
                message=(
                    f"Agent '{passport.name}' attempted to call tool "
                    f"'{context.resource}' which is not in its declared permissions. "
                    f"Allowed tools: {allowed_tool_ids or ['none declared']}"
                ),
                compliance_refs=["iris:tool-permission", "colorado-ai-act:transparency"],
                remediation=(
                    f"Add '{context.resource}' to the agent's tool_permissions "
                    f"in passport.yaml and get security engineer approval."
                ),
            )
        return None

    def _check_data_classification(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> Optional[Violation]:
        from iris_core.models.passport import DataClassification
        HIGH_SENSITIVITY = {DataClassification.PII, DataClassification.PHI, DataClassification.RESTRICTED}

        if not context.data_classification:
            return None
        try:
            requested = DataClassification(context.data_classification)
        except ValueError:
            return None

        if requested in HIGH_SENSITIVITY and passport.data_classification not in HIGH_SENSITIVITY:
            return Violation(
                rule_id="IRIS-DATA-001",
                severity=Severity.CRITICAL,
                message=(
                    f"Agent '{passport.name}' attempted to access "
                    f"'{requested.value}' data but is only approved for "
                    f"'{passport.data_classification.value}' data."
                ),
                compliance_refs=[
                    "colorado-ai-act:impact-assessment",
                    "gdpr:data-minimization",
                    "hipaa:minimum-necessary",
                ],
                remediation=(
                    "Update the agent passport data_classification field "
                    "and complete a data impact assessment before accessing this data."
                ),
            )
        return None

    def _check_user_rbac(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> Optional[Violation]:
        has_rbac_config = (
            passport.require_user_authentication
            or passport.allowed_user_roles
            or passport.allowed_user_emails
        )
        if not has_rbac_config:
            return None

        authenticated = context.user_authenticated or bool(context.user_email)

        if passport.require_user_authentication and not authenticated:
            return Violation(
                rule_id="IRIS-RBAC-001",
                severity=Severity.CRITICAL,
                message=(
                    "This agent requires authenticated user context. "
                    "Pass user_email and user_role to the evaluation context."
                ),
                compliance_refs=["iris:rbac", "soc2:access-control"],
                remediation=(
                    "Pass user_email and user_role when invoking the agent, "
                    "or set IRIS_USER_EMAIL and IRIS_USER_ROLE environment variables."
                ),
            )

        if context.user_email and context.user_email in passport.allowed_user_emails:
            return None

        if passport.allowed_user_roles and context.user_role not in passport.allowed_user_roles:
            allowed_roles = ", ".join(passport.allowed_user_roles)
            return Violation(
                rule_id="IRIS-RBAC-002",
                severity=Severity.CRITICAL,
                message=(
                    f"User role '{context.user_role}' is not authorized to invoke "
                    f"this agent. Authorized roles: {allowed_roles}"
                ),
                compliance_refs=["iris:rbac", "soc2:access-control"],
                remediation=(
                    "Request access from your security administrator, "
                    "or run: iris users add --email <you> --role <role> --agent "
                    f"{passport.name}"
                ),
            )

        return None

        return None

    @staticmethod
    def _delegation_required_scope(context: EvaluationContext) -> str:
        if context.additional.get("required_scope"):
            return str(context.additional["required_scope"])
        return f"{context.action}:{context.resource}"

    @staticmethod
    def _scope_covers(granted_scopes: List[str], required: str) -> bool:
        if not granted_scopes:
            return False
        if "*" in granted_scopes:
            return True
        if required in granted_scopes:
            return True
        action_part = required.split(":")[0] if ":" in required else required
        return action_part in granted_scopes

    def _check_delegation(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> List[Violation]:
        """Evaluate user delegation rules (IRIS-DEL-001 through IRIS-DEL-003)."""
        if not passport.user_delegation_enabled:
            return []

        violations: List[Violation] = []

        if not context.user_context:
            message = (
                "This agent requires user context for delegation. "
                "Pass user_context= to the guard call."
            )
            if context.environment == Environment.PRODUCTION:
                violations.append(
                    Violation(
                        rule_id="IRIS-DEL-004",
                        severity=Severity.CRITICAL,
                        message=(
                            f"Agent '{passport.name}' requires user context but none "
                            f"was provided. {message}"
                        ),
                        compliance_refs=["iris:delegation", "colorado-ai-act:CO-004"],
                        remediation=(
                            "Pass user_context=UserContext(user_id=..., "
                            "delegated_scopes=[...], consent_logged=True) "
                            "when invoking this agent."
                        ),
                    )
                )
            else:
                violations.append(
                    Violation(
                        rule_id="IRIS-DEL-004",
                        severity=Severity.HIGH,
                        message=message,
                        compliance_refs=["iris:delegation"],
                        remediation=(
                            "Pass user_context=UserContext(...) when invoking "
                            "this agent in delegated mode."
                        ),
                    )
                )
            return violations

        context.is_delegated = True
        user_ctx = context.user_context
        if user_ctx.user_email and not context.user_email:
            context.user_email = user_ctx.user_email
        if user_ctx.user_role and not context.user_role:
            context.user_role = user_ctx.user_role
        if user_ctx.consent_logged:
            context.user_consent_logged = True

        required_scope = self._delegation_required_scope(context)

        if passport.allowed_delegation_scopes:
            if not self._scope_covers(passport.allowed_delegation_scopes, required_scope):
                violations.append(
                    Violation(
                        rule_id="IRIS-DEL-001",
                        severity=Severity.CRITICAL,
                        message=(
                            f"Agent attempted action outside allowed delegation scope. "
                            f"Agent '{passport.name}' may delegate scopes: "
                            f"{passport.allowed_delegation_scopes}. "
                            f"Requested action '{context.action}' on "
                            f"'{context.resource}' requires scope: {required_scope}."
                        ),
                        compliance_refs=["iris:delegation"],
                        remediation=(
                            "Update allowed_delegation_scopes on the agent passport "
                            "after security review."
                        ),
                    )
                )
                return violations

        if not self._scope_covers(user_ctx.delegated_scopes, required_scope):
            scopes = user_ctx.delegated_scopes or ["none"]
            violations.append(
                Violation(
                    rule_id="IRIS-DEL-001",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Agent attempted action outside user-delegated scope. "
                        f"User '{user_ctx.user_id}' has granted scopes: {scopes}. "
                        f"Requested action '{context.action}' requires scope: "
                        f"{required_scope}. "
                        f"Remediation: Request the additional scope from the user "
                        f"before invoking this agent action."
                    ),
                    compliance_refs=["iris:delegation", "colorado-ai-act:CO-004"],
                    remediation=(
                        f"Request scope '{required_scope}' from user "
                        f"'{user_ctx.user_id}' before retrying."
                    ),
                )
            )

        if passport.require_user_consent_for_delegation and not user_ctx.consent_logged:
            violations.append(
                Violation(
                    rule_id="IRIS-DEL-002",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Delegation requires documented user consent. "
                        f"Set user_context.consent_logged=True after obtaining "
                        f"consent from user '{user_ctx.user_id}'."
                    ),
                    compliance_refs=["iris:delegation", "colorado-ai-act:CO-004"],
                    remediation=(
                        "Obtain user consent and set consent_logged=True on UserContext."
                    ),
                )
            )

        context.additional["_delegation_audit"] = {
            "acting_for_user": user_ctx.user_id,
            "delegated_scopes": user_ctx.delegated_scopes,
            "session_id": user_ctx.session_id,
            "idp_provider": user_ctx.idp_provider,
        }

        return violations

    def _check_model_governance(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> List[Violation]:
        from iris_core.engine.model_governance import check_model_governance

        if self._model_registry is None or self._directive_registry is None:
            self._load_model_governance()
        return check_model_governance(
            passport,
            context,
            self._model_registry,
            self._directive_registry,
        )

    def _check_colorado_act(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> List[Violation]:
        """
        Colorado AI Act (SB 26-189) checks.
        Effective January 1, 2027 (replaces SB 24-205). Covered ADMT systems must:
          1. Be inventoried (AgentPassport registration)
          2. Provide transparency disclosures (policy-intent.md exists)
          3. Allow post-adverse-action notice and appeal rights
        Impact assessments are best practice only under SB 26-189.
        """
        violations = []

        # Rule CO-002: Impact assessment (best practice — not legally required)
        if passport.is_high_risk_ai and not passport.evidence_vault_id:
            violations.append(Violation(
                rule_id="CO-002",
                severity=Severity.MEDIUM,
                message=(
                    f"Colorado AI Act note: agent '{passport.name}' has no impact "
                    f"assessment on file. Not legally required under SB 26-189 but "
                    f"recommended as best practice for NIST AI RMF alignment."
                ),
                compliance_refs=["colorado-ai-act:sb-26-189:impact-assessment"],
                remediation=(
                    "Run 'iris compliance assess --agent {passport.agent_id}' "
                    "to generate and record an impact assessment in the Evidence Vault."
                ),
            ))

        # Rule CO-003: Transparency disclosure (policy-intent.md must exist)
        if not passport.intent_ref:
            violations.append(Violation(
                rule_id="CO-003",
                severity=Severity.HIGH,
                message=(
                    f"Colorado AI Act violation: agent '{passport.name}' has no "
                    f"transparency disclosure (policy-intent.md). "
                    f"Consumers must be informed when ADMT makes or assists in "
                    f"consequential decisions under SB 26-189, effective Jan. 1, 2027."
                ),
                compliance_refs=["colorado-ai-act:sb-26-189:transparency"],
                remediation=(
                    "Run 'iris policy generate --agent {passport.agent_id}' to "
                    "generate a policy-intent.md transparency disclosure."
                ),
            ))

        consequential_actions = {"call", "write", "delete", "approve", "execute"}
        if context.action in consequential_actions and not context.user_consent_logged:
            violations.append(
                Violation(
                    rule_id="CO-004",
                    severity=Severity.HIGH,
                    message=(
                        f"Colorado AI Act: agent '{passport.name}' attempted a "
                        f"consequential action without logged user consent."
                    ),
                    compliance_refs=["colorado-ai-act:sb-26-189:consent"],
                    remediation=(
                        "Set user_consent_logged=True after obtaining documented consent."
                    ),
                )
            )

        return violations

    _MH_DIRECT_PATIENT_PATTERNS = (
        "patient-chat",
        "patient-message",
        "patient-communication",
        "therapy-chat",
        "counseling-message",
        "direct-patient-*",
    )

    _MH_TREATMENT_PLAN_PATTERNS = (
        "treatment-plan*",
        "diagnosis*",
        "clinical-recommendation*",
    )

    _MH_TRANSCRIPTION_PATTERNS = (
        "transcription*",
        "session-transcription",
        "*-transcription",
    )

    _VIDEO_ANALYSIS_PATTERNS = (
        "video-analysis*",
        "video-interview*",
        "interview-analysis*",
        "*-video-score*",
        "ai-video*",
    )

    _AEDT_PATTERNS = (
        "resume-screen*",
        "candidate-rank*",
        "hiring-score*",
        "aedt*",
        "ats-*",
        "employment-score*",
    )

    @classmethod
    def _tool_matches_patterns(cls, tool_name: str, patterns: tuple[str, ...]) -> bool:
        if not tool_name:
            return False
        return any(fnmatch.fnmatch(tool_name, pattern) for pattern in patterns)

    def _check_mental_health_ai(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> List[Violation]:
        """
        Colorado HB 26-1195 — Mental Health AI runtime enforcement.
        Effective August 12, 2026.
        """
        from iris_core.entitlements import Feature

        violations: List[Violation] = []
        tool_name = context.tool_name

        if self._tool_matches_patterns(tool_name, self._MH_DIRECT_PATIENT_PATTERNS):
            if not context.user_consent_logged:
                violations.append(
                    Violation(
                        rule_id="MH-001",
                        severity=Severity.CRITICAL,
                        message=(
                            "Direct AI patient communication is prohibited under "
                            "Colorado HB 1195 (effective Aug 12, 2026). "
                            "This tool call would communicate directly with a "
                            "mental health patient without explicit consent. "
                            "Remediation: Set user_consent_logged=True after "
                            "obtaining documented patient consent."
                        ),
                        compliance_refs=["colorado-mental-health-ai:MH-001"],
                        remediation=(
                            "Set user_consent_logged=True after obtaining "
                            "documented patient consent."
                        ),
                    )
                )

        if self._tool_matches_patterns(tool_name, self._MH_TRANSCRIPTION_PATTERNS):
            if not context.user_consent_logged:
                violations.append(
                    Violation(
                        rule_id="MH-003",
                        severity=Severity.CRITICAL,
                        message=(
                            "AI session transcription requires documented patient "
                            "consent under Colorado HB 26-1195. "
                            "Remediation: Set user_consent_logged=True after "
                            "obtaining documented patient consent."
                        ),
                        compliance_refs=["colorado-mental-health-ai:MH-003"],
                        remediation=(
                            "Set user_consent_logged=True after obtaining "
                            "documented patient consent for transcription."
                        ),
                    )
                )

        if self._tool_matches_patterns(tool_name, self._MH_TREATMENT_PLAN_PATTERNS):
            if not passport.has_feature(Feature.HITL_GATE):
                message = (
                    "Treatment plan generation requires IRIS Pro HITL gate for "
                    "licensed clinician review under Colorado HB 26-1195 (MH-002)."
                )
                remediation = (
                    "Upgrade to IRIS Pro for HITL gate: iris license activate <your-key>"
                )
                if context.environment in (Environment.DEV, Environment.TEST):
                    violations.append(
                        Violation(
                            rule_id="MH-002",
                            severity=Severity.HIGH,
                            message=message,
                            compliance_refs=["colorado-mental-health-ai:MH-002"],
                            remediation=remediation,
                        )
                    )
                else:
                    violations.append(
                        Violation(
                            rule_id="MH-002",
                            severity=Severity.CRITICAL,
                            message=(
                                f"{message} "
                                "Treatment plan generation requires IRIS Pro."
                            ),
                            compliance_refs=["colorado-mental-health-ai:MH-002"],
                            remediation=remediation,
                        )
                    )

        return violations

    def _check_illinois_ai_video(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> List[Violation]:
        violations: List[Violation] = []
        tool_name = context.tool_name
        video_context = (
            self._tool_matches_patterns(tool_name, self._VIDEO_ANALYSIS_PATTERNS)
            or (context.data_classification or "").lower() in {"video", "biometric"}
            or context.action in {"analyze", "score", "evaluate"}
        )
        if not video_context:
            return violations

        consent_type = str(context.additional.get("consent_type", ""))
        if not context.user_consent_logged or consent_type != "ai_video_interview":
            violations.append(
                Violation(
                    rule_id="ILVI-002",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Illinois AI Video Interview Act: agent '{passport.name}' "
                        "attempted video analysis without ai_video_interview consent."
                    ),
                    compliance_refs=["illinois-ai-video:820-ilcs-42-15b-consent"],
                    remediation=(
                        "Set user_consent_logged=True with consent_type='ai_video_interview' "
                        "before recording or analyzing video interviews."
                    ),
                )
            )
        return violations

    def _check_nyc_ll144(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
    ) -> List[Violation]:
        violations: List[Violation] = []
        tool_name = context.tool_name
        aedt_context = (
            self._tool_matches_patterns(tool_name, self._AEDT_PATTERNS)
            or passport.is_high_risk_ai
            or context.action in {"rank", "screen", "score", "shortlist"}
        )
        if not aedt_context:
            return violations

        if not context.user_consent_logged:
            violations.append(
                Violation(
                    rule_id="LL144-003",
                    severity=Severity.HIGH,
                    message=(
                        f"NYC LL 144: agent '{passport.name}' attempted AEDT use "
                        "without logged candidate consent."
                    ),
                    compliance_refs=["nyc-ll144:20-873-notice"],
                    remediation=(
                        "Set user_consent_logged=True after providing 10-day advance "
                        "candidate notice before AEDT screening."
                    ),
                )
            )
        return violations

    def _apply_violation_responses(
        self,
        passport: AgentPassport,
        violations: List[Violation],
        enforcement: EnforcementLevel,
    ) -> tuple:
        blocking: List[Violation] = []
        inform: List[Violation] = []
        warn_only: List[Violation] = []
        hitl_violations: List[Violation] = []
        requires_hitl = False
        is_compliance_block = False

        hitl_config = passport.hitl_config
        step_up_severities = set(hitl_config.required_for_risk_levels) if hitl_config else set()

        for violation in violations:
            response = get_effective_response(
                violation.rule_id,
                passport.compliance_response_overrides,
                severity=violation.severity.value,
            )
            # Operator-declared severity tiering (hitl_config.required_for_risk_levels):
            # a violation that would otherwise be a silent INFORM log escalates to
            # HITL when its severity is in the agent's declared step-up list. Only
            # escalates INFORM -> HITL; never downgrades an existing BLOCK/HITL.
            if response == ViolationResponse.INFORM and violation.severity.value in step_up_severities:
                response = ViolationResponse.HITL
            action = self._enforcement_engine.get_effective_action(
                violation.rule_id, response, enforcement
            )

            if action.action == "NOTHING":
                continue
            if action.notify and action.action == "WARN":
                logger.warning(
                    "[IRIS] %s in %s: %s",
                    violation.rule_id,
                    enforcement.value,
                    violation.message,
                )

            if action.action == "BLOCK":
                blocking.append(violation)
                is_compliance_block = True
            elif action.action == "HITL":
                hitl_violations.append(violation)
                requires_hitl = True
            elif action.action == "WARN":
                warn_only.append(violation)
            else:
                inform.append(violation)

        if blocking:
            active_violations = blocking
        elif hitl_violations:
            hitl_violations.sort(
                key=lambda v: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(
                    v.severity.value, 9
                )
            )
            active_violations = hitl_violations
        elif warn_only:
            active_violations = warn_only
        else:
            active_violations = inform

        hitl_violation = hitl_violations[0] if hitl_violations else None
        return (
            active_violations,
            inform,
            requires_hitl,
            hitl_violation.rule_id if hitl_violation else "",
            "compliance" if hitl_violation else "business",
            hitl_violation,
            is_compliance_block,
            warn_only,
        )

    def _check_hitl_required(
        self,
        passport: AgentPassport,
        context: EvaluationContext,
        cedar_annotations: Dict[str, str],
    ) -> tuple[bool, str]:
        """Returns (requires_hitl, reason). Developer-declared rules only."""
        if cedar_annotations.get("hitl_required") == "true":
            reason = cedar_annotations.get(
                "hitl_reason",
                "Cedar rule requires human approval for this action",
            )
            return True, reason

        config = passport.hitl_config
        if config and config.enabled:
            for rule in config.condition_rules or []:
                if self._evaluate_hitl_condition(rule, context):
                    return True, rule.reason

            env_name = context.resolved_environment_name
            if (
                config.step_up_actions
                and context.action in config.step_up_actions
                and env_name in ("staging", "production")
            ):
                return True, (
                    f"Action '{context.action}' is declared step-up in "
                    f"'{env_name}' (hitl_config.step_up_actions)"
                )

            if (
                config.sensitive_data_classifications
                and context.data_classification
                and context.data_classification in config.sensitive_data_classifications
            ):
                return True, (
                    f"Data classification '{context.data_classification}' requires "
                    "human approval (hitl_config.sensitive_data_classifications)"
                )

        if context.require_hitl:
            return True, context.require_hitl_reason or "Manual HITL override"

        return False, ""

    def _evaluate_hitl_condition(
        self,
        rule: HITLConditionRule,
        context: EvaluationContext,
    ) -> bool:
        try:
            context_dict = context.to_dict()
            return bool(eval(rule.condition, {"__builtins__": {}}, context_dict))
        except Exception:
            logger.warning(
                "HITL condition '%s' failed to evaluate. "
                "Skipping this condition rule. Fix it in passport.yaml.",
                rule.condition,
            )
            return False

    def _match_cedar_annotations(
        self,
        policy: str,
        context: EvaluationContext,
    ) -> Dict[str, str]:
        annotations: Dict[str, str] = {}
        if not policy:
            return annotations

        permit_pattern = re.compile(
            r"permit\s*\((.*?)\)\s*(?:when\s*\{[^}]*\})?\s*annotations\s*\{([^}]*)\}",
            re.DOTALL | re.IGNORECASE,
        )
        for match in permit_pattern.finditer(policy):
            header, ann_block = match.group(1), match.group(2)
            if not self._cedar_rule_matches_context(header, context):
                continue
            for match in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', ann_block):
                annotations[match.group(1)] = match.group(2)
        return annotations

    @staticmethod
    def _cedar_rule_matches_context(header: str, context: EvaluationContext) -> bool:
        action_match = re.search(r'action\s*==\s*iris::Action::"([^"]+)"', header)
        resource_match = re.search(r'resource\s*==\s*iris::API::"([^"]+)"', header)
        if action_match:
            cedar_action = action_match.group(1)
            if cedar_action != context.action and cedar_action != "call":
                return False
        if resource_match:
            resource_name = resource_match.group(1)
            if resource_name not in (context.resource, context.tool_name, "anthropic-api"):
                return False
        return True
