"""Model governance evaluation — tier, export control, and directive checks."""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

from iris_core.models.passport import AgentPassport, Environment
from iris_core.models.policy import Severity, Violation
from iris_core.models.model_registry import ModelCapability, ModelRegistry, ModelTier

if TYPE_CHECKING:
    from iris_core.engine.cedar import EvaluationContext
    from iris_core.models.directives import DirectiveRegistry


def resolve_model_context(
    model_id: Optional[str],
    registry: ModelRegistry,
    directives: "DirectiveRegistry",
) -> dict:
    """Resolve model tier, directive status, and fallback from registries."""
    if not model_id:
        return {}

    capability = registry.resolve(model_id)
    directive = directives.active_for_model(model_id)
    if capability is None and directive is None:
        return {"model_id": model_id}

    resolved_id = capability.model_id if capability else model_id
    ctx: dict = {"model_id": resolved_id}
    if capability:
        ctx["model_tier"] = capability.tier.value
        ctx["export_control"] = capability.export_control.value
        ctx["model_requires_hitl"] = capability.requires_hitl
        ctx["model_retention_days"] = capability.retention_days
        if capability.fallback_model:
            ctx["fallback_model"] = capability.fallback_model
    if directive:
        ctx["directive_status"] = directive.status
        ctx["directive_id"] = directive.directive_id
        ctx["directive_reason"] = directive.reason
        if directive.fallback_model:
            ctx["fallback_model"] = directive.fallback_model
    return ctx


def check_model_governance(
    passport: AgentPassport,
    context: "EvaluationContext",
    registry: ModelRegistry,
    directives: "DirectiveRegistry",
) -> List[Violation]:
    """Evaluate model tier, export control, and active directives."""
    model_id = context.model_id or context.additional.get("model")
    if not model_id:
        return []

    capability = registry.resolve(str(model_id))
    directive = directives.active_for_model(capability.model_id if capability else str(model_id))
    violations: List[Violation] = []

    if directive and directive.is_active() and not context.auto_fallback_applied:
        violations.append(
            Violation(
                rule_id="IRIS-MODEL-001",
                severity=Severity.CRITICAL,
                message=(
                    f"Model '{model_id}' is suspended by directive "
                    f"'{directive.directive_id}': {directive.reason}"
                ),
                compliance_refs=["export-control:directive", "nist-ai-rmf:gov-1"],
                remediation=(
                    f"Use fallback model '{directive.fallback_model or capability.fallback_model if capability else 'approved baseline'}' "
                    f"or remove the directive from governance/directives/active.yaml after review."
                ),
            )
        )
        return violations

    if capability is None:
        return violations

    if passport.allowed_models and capability.model_id not in passport.allowed_models:
        if str(model_id) not in passport.allowed_models:
            violations.append(
                Violation(
                    rule_id="IRIS-MODEL-002",
                    severity=Severity.HIGH,
                    message=(
                        f"Agent '{passport.name}' attempted to use model '{model_id}' "
                        f"which is not in its allowed_models list."
                    ),
                    compliance_refs=["iris:model-allowlist"],
                    remediation=(
                        f"Add '{capability.model_id}' to allowed_models in passport.yaml "
                        f"and get security engineer approval."
                    ),
                )
            )

    if passport.allowed_model_tiers:
        if capability.tier.value not in passport.allowed_model_tiers:
            violations.append(
                Violation(
                    rule_id="IRIS-MODEL-003",
                    severity=Severity.HIGH,
                    message=(
                        f"Agent '{passport.name}' attempted to use model tier "
                        f"'{capability.tier.value}' but is only approved for "
                        f"{passport.allowed_model_tiers}."
                    ),
                    compliance_refs=["iris:model-tier-gate"],
                    remediation=(
                        f"Update allowed_model_tiers in passport.yaml to include "
                        f"'{capability.tier.value}' or switch to an approved model."
                    ),
                )
            )

    if capability.tier == ModelTier.FRONTIER_RESTRICTED:
        auth = (context.user_work_authorization or "").lower()
        if capability.allowed_work_authorizations and auth not in capability.allowed_work_authorizations:
            violations.append(
                Violation(
                    rule_id="IRIS-MODEL-004",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Model '{model_id}' is export-control restricted. "
                        f"User work authorization '{auth or 'not provided'}' is not permitted. "
                        f"Required: {capability.allowed_work_authorizations}"
                    ),
                    compliance_refs=["export-control:bis-restricted", "nist-ai-rmf:gov-1"],
                    remediation=(
                        "Provide a valid user_work_authorization (e.g. us-citizen) "
                        "or use an unrestricted model tier."
                    ),
                )
            )

    if capability.requires_hitl and context.environment in (Environment.STAGING, Environment.PRODUCTION):
        if not context.hitl_approved:
            violations.append(
                Violation(
                    rule_id="IRIS-MODEL-005",
                    severity=Severity.HIGH,
                    message=(
                        f"Model '{model_id}' requires human-in-the-loop approval "
                        f"in {context.environment.value} but hitl_approved is false."
                    ),
                    compliance_refs=["nist-ai-rmf:gov-2", "colorado-ai-act:transparency"],
                    remediation=(
                        "Set hitl_approved=True after security review, or use iris HITL workflow."
                    ),
                )
            )

    return violations


def resolve_fallback_model(
    model_id: str,
    registry: ModelRegistry,
    directives: "DirectiveRegistry",
) -> Optional[str]:
    """Return fallback model when a directive suspends access."""
    capability = registry.resolve(model_id)
    resolved_id = capability.model_id if capability else model_id
    directive = directives.active_for_model(resolved_id)
    if not directive or not directive.is_active():
        return None
    if directive.fallback_model:
        return directive.fallback_model
    if capability and capability.fallback_model:
        return capability.fallback_model
    return None
