"""
The single gatekeeper for all feature access in IRIS.

Every feature check goes through Entitlements.
"""

from __future__ import annotations

from typing import List, Optional

from iris_core.errors import IrisError
from iris_core.entitlements.capability_map import FEATURE_TO_CAPABILITY_MAP
from iris_core.entitlements.features import FEATURE_TIERS, TIER_RANK, Feature, Tier
from iris_core.entitlements.license import LicenseKey
from iris_core.flags import launch_gate
from iris_core.flags.launch_gate import CapabilityStatus

_RELATED_PRO_BY_PREFIX = {
    "bundle_": [
        Feature.BUNDLE_HIPAA,
        Feature.BUNDLE_SOC2,
        Feature.BUNDLE_NIST_AI_RMF,
    ],
    "vault_": [
        Feature.VAULT_UNLIMITED_RETENTION,
        Feature.VAULT_PDF_EXPORT,
        Feature.VAULT_CLOUD_SYNC,
    ],
    "cli_test_": [
        Feature.CLI_TEST_FULL_REPORT,
        Feature.CLI_TEST_ALL_GAPS,
        Feature.CLI_TEST_PDF_EXPORT,
    ],
    "red_team_": [
        Feature.RED_TEAM_FULL_FINDINGS,
        Feature.RED_TEAM_BYPASS_DETAILS,
        Feature.RED_TEAM_REMEDIATION,
    ],
    "drift_": [
        Feature.DRIFT_SLACK_ALERT,
        Feature.DRIFT_EMAIL_ALERT,
        Feature.DRIFT_WEBHOOK_ALERT,
    ],
    "cost_": [
        Feature.COST_ANOMALY_ALERT,
        Feature.COST_ORG_SUMMARY,
        Feature.COST_TEAM_ROLLUP,
    ],
}

_DEFAULT_RELATED_PRO = [
    Feature.BUNDLE_HIPAA,
    Feature.VAULT_UNLIMITED_RETENTION,
    Feature.TEAM_RBAC,
]


def _tier_includes(holder: Tier, required: Tier) -> bool:
    return TIER_RANK[holder] >= TIER_RANK[required]


def _related_pro_features(feature: Feature) -> List[Feature]:
    name = feature.value
    for prefix, related in _RELATED_PRO_BY_PREFIX.items():
        if name.startswith(prefix):
            return related
    return list(_DEFAULT_RELATED_PRO)


def _build_entitlement_message(
    feature: Feature,
    context: Optional[str],
    related: List[Feature],
) -> str:
    context_line = (
        f"│  You were trying to: {context:<38}│\n"
        if context
        else "│                                                             │\n"
    )
    unlock_lines = "\n".join(
        f"│    • {related_feature.value:<54}│"
        for related_feature in related[:3]
    )
    return f"""┌─ IRIS Pro Feature ─────────────────────────────────────────┐
│                                                             │
│  {feature.value} requires IRIS Pro.                        │
│                                                             │
{context_line}│  What Pro unlocks:                                         │
{unlock_lines}
│                                                             │
│  Get IRIS Pro:                                             │
│    iris license activate <your-key>                        │
│    https://iris.ai/pricing                                  │
│                                                             │
│  Free tier:  Colorado AI Act, all LLM integrations,       │
│              Cursor MCP, local Evidence Vault (30 days)   │
└────────────────────────────────────────────────────────────┘"""


class EntitlementError(IrisError):
    def __init__(
        self,
        feature: Feature,
        current_tier: Tier,
        required_tier: Tier,
        message: str,
    ):
        self.feature = feature
        self.current_tier = current_tier
        self.required_tier = required_tier
        self.message = message
        super().__init__(message)


class Entitlements:
    """
    The single gatekeeper for all feature access in IRIS.

    Usage::

        from iris_core.entitlements import Entitlements, Feature

        ents = Entitlements()
        if ents.has(Feature.BUNDLE_HIPAA):
            run_hipaa_checks()
        ents.require(Feature.VAULT_PDF_EXPORT, context="evidence PDF export")
    """

    def __init__(self) -> None:
        self._forced_tier: Optional[Tier] = None
        self._license_key: Optional[str] = None
        self._license_valid = False
        self._license_reason = "no_key"
        self._resolve_tier()

    def _resolve_tier(self) -> None:
        if self._forced_tier is not None:
            return

        key = LicenseKey.read_active_key()
        self._license_key = key
        if not key:
            self._tier = Tier.FREE
            self._license_valid = False
            self._license_reason = "no_key"
            return

        valid, tier, reason = LicenseKey.validate(key)
        self._license_valid = valid
        self._license_reason = reason
        self._tier = tier if valid else Tier.FREE

    def _tier_permits(self, feature: Feature) -> bool:
        required = FEATURE_TIERS[feature]
        return _tier_includes(self._tier, required)

    def has(self, feature: Feature) -> bool:
        """Return True if tier permits the feature and it is shippable."""
        tier_ok = self._tier_permits(feature)
        if FEATURE_TIERS[feature] == Tier.FREE:
            return tier_ok
        capability_name = FEATURE_TO_CAPABILITY_MAP.get(feature)
        if capability_name is None:
            return tier_ok
        return tier_ok and launch_gate.is_shippable(capability_name)

    def upgrade_message(self, feature: Feature) -> str:
        """Human-readable reason a feature is unavailable."""
        capability_name = FEATURE_TO_CAPABILITY_MAP.get(feature)
        if capability_name is not None:
            status = launch_gate.CAPABILITY_FLAGS.get(
                capability_name, CapabilityStatus.BACKLOG
            )
            if status == CapabilityStatus.BACKLOG:
                return (
                    f"{capability_name} is on the IRIS roadmap, not yet "
                    f"available — even to Business/Enterprise customers. "
                    f"Track it: github.com/gimartinb/iris-sdk/blob/main/BACKLOG.md"
                )
        required = FEATURE_TIERS[feature]
        tier_label = {
            Tier.FREE: "Community",
            Tier.PRO: "Business",
            Tier.ENTERPRISE: "Enterprise",
        }[required]
        return (
            f"{feature.value} requires {tier_label}. "
            f"Activate a license: iris license activate <your-key>"
        )

    def require(self, feature: Feature, context: Optional[str] = None) -> None:
        """Raise EntitlementError if the feature is not available."""
        if self.has(feature):
            return

        required = FEATURE_TIERS[feature]
        capability_name = FEATURE_TO_CAPABILITY_MAP.get(feature)
        if capability_name is not None:
            status = launch_gate.CAPABILITY_FLAGS.get(
                capability_name, CapabilityStatus.BACKLOG
            )
            if status == CapabilityStatus.BACKLOG:
                context_line = f" ({context})" if context else ""
                message = self.upgrade_message(feature) + context_line
                raise EntitlementError(
                    feature=feature,
                    current_tier=self._tier,
                    required_tier=required,
                    message=message,
                )

        related = _related_pro_features(feature)
        message = _build_entitlement_message(feature, context, related)
        raise EntitlementError(
            feature=feature,
            current_tier=self._tier,
            required_tier=required,
            message=message,
        )

    def current_tier(self) -> Tier:
        """Return the current license tier."""
        return self._tier

    def tier_name(self) -> str:
        """Return human-readable tier name."""
        return {
            Tier.FREE: "Free",
            Tier.PRO: "Pro",
            Tier.ENTERPRISE: "Enterprise",
        }[self._tier]

    def list_available(self) -> List[Feature]:
        """Return all features available at the current tier."""
        return [
            feature
            for feature, required in FEATURE_TIERS.items()
            if _tier_includes(self._tier, required)
        ]

    def list_locked(self) -> List[Feature]:
        """Return all features NOT available at the current tier."""
        return [
            feature
            for feature, required in FEATURE_TIERS.items()
            if not _tier_includes(self._tier, required)
        ]

    @property
    def license_key(self) -> Optional[str]:
        return self._license_key

    @property
    def license_valid(self) -> bool:
        return self._license_valid

    @property
    def license_reason(self) -> str:
        return self._license_reason

    @staticmethod
    def for_testing(tier: Tier) -> "Entitlements":
        """Create an Entitlements instance with a forced tier (tests only)."""
        instance = Entitlements.__new__(Entitlements)
        instance._forced_tier = tier
        instance._tier = tier
        instance._license_key = None
        instance._license_valid = tier != Tier.FREE
        instance._license_reason = "test_override"
        return instance
