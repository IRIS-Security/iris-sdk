"""
IRIS Launch Gate

Community is the only tier with built, tested, running code.
Business and Enterprise are architecture, not software, until
each individual capability graduates out of BACKLOG.md with
passing tests in CI.

SHOW_PAID_TIERS is the master switch. Even when true, individual
capabilities still check their OWN flag (see CAPABILITY_FLAGS) —
flipping the master switch does not retroactively make unbuilt
code real. The master switch only controls whether the PRICING
PAGE SECTION renders at all; it is a marketing-surface flag, not
a feature-enablement flag. Feature enablement is always per-
capability and always tied to BACKLOG.md status.
"""

from __future__ import annotations

import os
from enum import Enum


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


SHOW_PAID_TIERS: bool = _env_bool("IRIS_SHOW_PAID_TIERS", False)


class CapabilityStatus(str, Enum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    SHIPPABLE = "shippable"
    LIVE = "live"


CAPABILITY_FLAGS: dict[str, CapabilityStatus] = {
    # Demo / platform capabilities
    "org_discovery_engine": CapabilityStatus.SHIPPABLE,
    "ciso_coverage_trend": CapabilityStatus.SHIPPABLE,
    "integrations_api": CapabilityStatus.SHIPPABLE,
    "evidence_smart_filter": CapabilityStatus.SHIPPABLE,
    "otel_export": CapabilityStatus.SHIPPABLE,
    "onboarding_profiler": CapabilityStatus.SHIPPABLE,
    "theme_light_dark": CapabilityStatus.SHIPPABLE,
    "aarm_core_conformant": CapabilityStatus.IN_PROGRESS,
    "aarm_extended_conformant": CapabilityStatus.BACKLOG,
    "aiuc1_evidence_package": CapabilityStatus.SHIPPABLE,
    "multi_agent_chains": CapabilityStatus.SHIPPABLE,
    "aarm_r7_intent_drift": CapabilityStatus.IN_PROGRESS,
    # Business
    "compliance_full_eval": CapabilityStatus.SHIPPABLE,
    "certify_export": CapabilityStatus.SHIPPABLE,
    "hitl_notifications": CapabilityStatus.SHIPPABLE,
    "evidence_vault_cloud": CapabilityStatus.BACKLOG,
    "vault_siem_export": CapabilityStatus.SHIPPABLE,
    "github_app_org": CapabilityStatus.IN_PROGRESS,
    "mcp_pro_tools": CapabilityStatus.IN_PROGRESS,
    "audit_log_export": CapabilityStatus.SHIPPABLE,
    # Enterprise
    "org_policy_enforcement": CapabilityStatus.BACKLOG,
    "sso_saml_oidc": CapabilityStatus.IN_PROGRESS,
    "scim_provisioning": CapabilityStatus.BACKLOG,
    "rbac_custom_roles": CapabilityStatus.BACKLOG,
    "enterprise_vault_integrations": CapabilityStatus.BACKLOG,
    "byok_encryption": CapabilityStatus.BACKLOG,
    "fedramp_region_enforcement": CapabilityStatus.BACKLOG,
}

BACKLOG_MD_URL = "https://github.com/gimartinb/iris-sdk/blob/main/BACKLOG.md"

# Related: packages/iris-cloud-console/src/components/featureFlags.jsx
# controls UI nav/feature visibility. Reconcile via BACKLOG.md follow-up
# "feature-flag-system-reconciliation" — do not merge prematurely.


def is_shippable(capability: str) -> bool:
    """Return True only if the capability is SHIPPABLE or LIVE."""
    status = CAPABILITY_FLAGS.get(capability, CapabilityStatus.BACKLOG)
    return status in (CapabilityStatus.SHIPPABLE, CapabilityStatus.LIVE)


def trend_chart_is_shippable(org_id: str) -> bool:
    """
    CISO trend chart ships after 7 real daily snapshots.
    In demo mode (org_id starts with 'demo-' or IRIS_DEMO_MODE=1),
    always return True so the demo works on day 1.
    """
    if os.environ.get("IRIS_DEMO_MODE") == "1":
        return True
    if org_id and org_id.startswith("demo"):
        return True
    from iris_core.discovery.coverage_snapshot import CoverageSnapshot

    return CoverageSnapshot.count_for_org(org_id) >= 7
