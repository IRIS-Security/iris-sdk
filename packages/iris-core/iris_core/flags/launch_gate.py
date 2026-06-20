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
    # Business
    "compliance_full_eval": CapabilityStatus.BACKLOG,
    "certify_export": CapabilityStatus.BACKLOG,
    "hitl_notifications": CapabilityStatus.BACKLOG,
    "evidence_vault_cloud": CapabilityStatus.BACKLOG,
    "vault_siem_export": CapabilityStatus.BACKLOG,
    "github_app_org": CapabilityStatus.BACKLOG,
    "mcp_pro_tools": CapabilityStatus.BACKLOG,
    "audit_log_export": CapabilityStatus.BACKLOG,
    # Enterprise
    "org_policy_enforcement": CapabilityStatus.BACKLOG,
    "sso_saml_oidc": CapabilityStatus.BACKLOG,
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
