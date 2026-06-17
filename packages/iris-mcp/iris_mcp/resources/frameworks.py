"""Compliance framework documentation as MCP resources."""

from __future__ import annotations

from mcp.types import Resource

from iris_core.compliance.framework_check import load_bundle_data
from iris_core.compliance.registry import _BUNDLE_LOADERS, _is_paid_bundle

_FRAMEWORK_NAMES = {
    "colorado-ai-act": "Colorado AI Act (SB 26-189)",
    "colorado-chatbot": "Colorado Chatbot Act (HB 1263)",
    "colorado-health-ai": "Colorado Health AI (HB 1139)",
    "colorado-mental-health-ai": "Colorado Mental Health AI (HB 1195)",
    "ccpa-admt": "California CCPA/ADMT",
    "china-pipl": "China PIPL",
    "illinois-ai-video": "Illinois AI Video Interview Act",
    "nyc-ll144": "NYC Local Law 144 — AEDTs",
    "hipaa": "HIPAA",
    "soc2": "SOC 2",
    "gdpr": "GDPR",
    "eu-ai-act": "EU AI Act",
    "nist-ai-rmf": "NIST AI RMF",
    "fedramp": "FedRAMP Moderate",
}


def _load_bundle_metadata(bundle_id: str) -> dict:
    """Load bundle docs without Pro entitlement gating (discovery/docs only)."""
    return load_bundle_data(bundle_id)


def _framework_markdown(bundle_id: str, rules: dict) -> str:
    name = rules.get("full_name") or _FRAMEWORK_NAMES.get(bundle_id, bundle_id)
    tier = "Pro" if _is_paid_bundle(bundle_id) else "Free"
    lines = [
        f"# {name}",
        "",
        f"**Bundle ID:** `{bundle_id}`",
        f"**Tier:** {tier}",
        f"**Jurisdiction:** {rules.get('jurisdiction', 'See bundle')}",
        f"**Effective date:** {rules.get('effective_date', 'See bundle')}",
        "",
        "## IRIS coverage",
        "",
    ]
    if rules.get("warning"):
        lines.extend([f"> {rules['warning']}", ""])
    lines.append("## Rules")
    lines.append("")
    for rule in rules.get("rules", []):
        lines.append(f"### {rule.get('rule_id')} — {rule.get('name')}")
        lines.append(f"- **Severity:** {rule.get('severity')}")
        lines.append(f"- {rule.get('description', '')}")
        if rule.get("how_iris_satisfies"):
            lines.append(f"- **IRIS control:** {rule['how_iris_satisfies']}")
        lines.append("")
    return "\n".join(lines)


def build_framework_resources() -> list[Resource]:
    resources: list[Resource] = []
    for bundle_id in sorted(_BUNDLE_LOADERS):
        rules = _load_bundle_metadata(bundle_id)
        name = rules.get("full_name") or _FRAMEWORK_NAMES.get(bundle_id, bundle_id)
        resources.append(
            Resource(
                uri=f"iris://frameworks/{bundle_id}",
                name=name,
                description="Rules, effective dates, and IRIS coverage",
                mimeType="text/markdown",
            )
        )
    return resources


FRAMEWORK_RESOURCES = build_framework_resources()
_FRAMEWORK_TEXT: dict[str, str] = {}


def get_framework_text(uri: str) -> str | None:
    if not _FRAMEWORK_TEXT:
        for bundle_id in _BUNDLE_LOADERS:
            rules = _load_bundle_metadata(bundle_id)
            _FRAMEWORK_TEXT[f"iris://frameworks/{bundle_id}"] = _framework_markdown(
                bundle_id, rules
            )
    return _FRAMEWORK_TEXT.get(uri)
