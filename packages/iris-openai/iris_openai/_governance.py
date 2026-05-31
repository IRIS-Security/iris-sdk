"""Shared IRIS evaluation helpers for OpenAI SDK integration."""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yaml

from iris import IrisViolationError
from iris_core.engine.cedar import CedarEngine, EvaluationContext
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment
from iris_core.models.policy import PolicyResult, Severity, Violation
from iris_core.models.region import RegionPolicy, TransferRule

logger = logging.getLogger("iris.openai")

_VAULT_LOCK = threading.Lock()

_AZURE_LOCATION_TOKENS: Dict[str, str] = {
    "westeurope": "eu-west-1",
    "northeurope": "eu-north-1",
    "swedencentral": "eu-north-1",
    "francecentral": "eu-central-1",
    "germanywestcentral": "eu-central-1",
    "eastus": "us-east-1",
    "eastus2": "us-east-2",
    "westus": "us-west-1",
    "westus2": "us-west-2",
    "centralus": "us-central-1",
    "southcentralus": "us-central-1",
}

_EU_REGION_PREFIXES = ("eu-",)


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


def load_region_policy() -> Optional[RegionPolicy]:
    """Load optional RegionPolicy from GitOps or ~/.iris."""
    candidates = [
        Path.cwd() / "governance" / "region-policy.yaml",
        Path.home() / ".iris" / "region-policy.yaml",
    ]
    env_path = os.environ.get("IRIS_REGION_POLICY")
    if env_path:
        candidates.insert(0, Path(env_path))

    for path in candidates:
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text()) or {}
        spec = data.get("spec", data)
        transfers = []
        for rule in spec.get("restricted_transfers", []):
            transfers.append(
                TransferRule(
                    from_region=rule["from_region"],
                    to_region=rule["to_region"],
                    compliance_ref=rule.get("compliance_ref", "iris:cross-region"),
                    action=rule.get("action", "block"),
                    note=rule.get("note"),
                )
            )
        return RegionPolicy(
            name=spec.get("name", data.get("metadata", {}).get("name", "default")),
            restricted_transfers=transfers,
        )
    return None


def parse_azure_endpoint_region(azure_endpoint: Optional[str]) -> Optional[str]:
    """
    Extract a canonical region from an Azure OpenAI endpoint URL.

    https://my-resource.openai.azure.com → no region in hostname
    https://my-resource.cognitiveservices.azure.com/openai → location token in host
    """
    if not azure_endpoint:
        return None
    host = (urlparse(azure_endpoint).hostname or "").lower()
    if not host:
        return None
    if host.endswith(".openai.azure.com"):
        return None
    for token, region in _AZURE_LOCATION_TOKENS.items():
        if token in host:
            return region
    for part in host.split("."):
        if part.startswith(("eu-", "us-", "ap-", "cn-")):
            return part
    return None


def is_eu_region(region: Optional[str]) -> bool:
    return bool(region and region.startswith(_EU_REGION_PREFIXES))


def check_region_policy_transfer(
    region_policy: RegionPolicy,
    data_region: str,
    destination_region: str,
) -> Optional[Violation]:
    for rule in region_policy.restricted_transfers:
        if rule.from_region == data_region and rule.to_region == destination_region:
            if rule.action == "block":
                return Violation(
                    rule_id="IRIS-XR-001",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Cross-region data transfer blocked by region policy "
                        f"'{region_policy.name}': {data_region} → {destination_region}. "
                        f"{rule.note or ''}".strip()
                    ),
                    compliance_refs=[rule.compliance_ref],
                    remediation=(
                        "Use an Azure endpoint in an approved region or update "
                        "governance/region-policy.yaml with a documented exception."
                    ),
                )
    return None


def azure_cross_region_violation(
    passport: AgentPassport,
    azure_endpoint: Optional[str],
    region_policy: Optional[RegionPolicy] = None,
) -> Optional[Violation]:
    """Flag EU/US mismatches when Azure endpoint region is known."""
    destination = parse_azure_endpoint_region(azure_endpoint)
    if not destination:
        return None

    data_region = passport.allowed_regions[0] if passport.allowed_regions else None
    if not data_region:
        if is_eu_region(destination):
            return Violation(
                rule_id="IRIS-XR-002",
                severity=Severity.HIGH,
                message=(
                    f"Azure OpenAI endpoint resolves to EU region '{destination}' "
                    f"but agent '{passport.name}' has no allowed_regions declared. "
                    f"EU-hosted inference may process EU personal data under GDPR."
                ),
                compliance_refs=["gdpr:chapter-5-transfer", "iris:cross-region"],
                remediation=(
                    "Set allowed_regions on the agent passport to document approved "
                    "data residency, or use a non-EU Azure endpoint."
                ),
            )
        return None

    policy = region_policy or load_region_policy()
    if policy:
        violation = check_region_policy_transfer(policy, data_region, destination)
        if violation:
            return violation

    if is_eu_region(data_region) != is_eu_region(destination):
        return Violation(
            rule_id="IRIS-XR-001",
            severity=Severity.CRITICAL,
            message=(
                f"Cross-region Azure OpenAI call blocked: passport data region "
                f"'{data_region}' does not match endpoint region '{destination}'."
            ),
            compliance_refs=["gdpr:chapter-5-transfer", "iris:cross-region"],
            remediation=(
                "Point azure_endpoint at a region that matches the agent's "
                "allowed_regions, or update the passport after security review."
            ),
        )
    return None


def apply_no_policy_gate(
    engine: CedarEngine,
    passport: AgentPassport,
    env: Environment,
    result: PolicyResult,
) -> PolicyResult:
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


def merge_results(base: PolicyResult, extra_violations: List[Violation]) -> PolicyResult:
    if not extra_violations:
        return base
    violations = list(base.violations) + list(extra_violations)
    critical = [v for v in violations if v.severity == Severity.CRITICAL]
    high = [v for v in violations if v.severity in (Severity.HIGH, Severity.CRITICAL)]
    if critical:
        decision = "DENY"
    elif high and base.decision == "PERMIT":
        decision = "DENY"
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


def evaluate_openai_call(
    engine: CedarEngine,
    vault: EvidenceVault,
    passport: AgentPassport,
    env: Environment,
    *,
    resource: str = "openai-api",
    operation: str = "chat.completions",
    model: Optional[str] = None,
    tool_names: Optional[List[str]] = None,
    data_classification: Optional[str] = None,
    azure_endpoint: Optional[str] = None,
    extra_violations: Optional[List[Violation]] = None,
) -> PolicyResult:
    data_region = passport.allowed_regions[0] if passport.allowed_regions else None
    destination_region = parse_azure_endpoint_region(azure_endpoint)

    ctx = EvaluationContext(
        agent_id=passport.agent_id,
        action="call",
        resource=resource,
        resource_type="api",
        environment=env,
        data_region=data_region,
        destination_region=destination_region,
        data_classification=data_classification or passport.data_classification.value,
        additional={
            "operation": operation,
            "model": model,
            "tool_names": tool_names or [],
            "azure_endpoint": azure_endpoint,
        },
    )

    result = engine.evaluate(passport, ctx)
    result = apply_no_policy_gate(engine, passport, env, result)

    violations: List[Violation] = list(extra_violations or [])
    azure_v = azure_cross_region_violation(passport, azure_endpoint)
    if azure_v:
        violations.append(azure_v)

    for name in tool_names or []:
        tool_ctx = EvaluationContext(
            agent_id=passport.agent_id,
            action="call",
            resource=name,
            resource_type="tool",
            environment=env,
            data_classification=data_classification or passport.data_classification.value,
        )
        tool_result = engine.evaluate(passport, tool_ctx)
        tool_result = apply_no_policy_gate(engine, passport, env, tool_result)
        violations.extend(tool_result.violations)
        if tool_result.decision == "DENY":
            result = PolicyResult(
                decision="DENY",
                violations=list(result.violations) + violations,
                agent_id=result.agent_id,
                action=result.action,
                resource=result.resource,
                environment=result.environment,
            )

    if env == Environment.PRODUCTION and (tool_names or []) and not passport.tool_permissions:
        for name in tool_names:
            violations.append(
                Violation(
                    rule_id="IRIS-TOOL-001",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Agent '{passport.name}' invoked tool '{name}' in production "
                        f"with no tool_permissions declared on the passport."
                    ),
                    compliance_refs=["iris:tool-permission", "colorado-ai-act:transparency"],
                    remediation=(
                        "Declare permitted tools in passport.yaml tool_permissions "
                        "before enabling tools in production."
                    ),
                )
            )
        result = PolicyResult(
            decision="DENY",
            violations=list(result.violations) + violations,
            agent_id=result.agent_id,
            action=result.action,
            resource=result.resource,
            environment=result.environment,
        )

    result = merge_results(result, violations)

    with _VAULT_LOCK:
        vault.record(ctx, result)
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
