"""Map AGT audit-entry metadata to a WorkloadProfile scan payload."""

from __future__ import annotations

from typing import Any

from iris.scan import scan_data_categories_from_text

# Event types/actions that count as autonomous tool-driven behavior, mirroring
# the threshold shape used by the Langfuse adapter's tool-call counter.
_TOOL_EVENT_TYPES = frozenset({"tool_invocation", "tool_blocked"})
_AUTONOMOUS_SIGNAL_ACTIONS = frozenset({"quarantine"})
_AUTONOMOUS_SIGNAL_EVENT_TYPES = frozenset({"rogue_detection"})

_CUSTOMER_FACING_HINTS = ("customer", "public", "external")


def _entry_text(entry: dict[str, Any]) -> str:
    """Structural/metadata text only — never the forbidden `data` field."""
    parts: list[str] = []
    for key in ("resource", "policy_decision", "matched_rule", "agent_did", "target_did"):
        value = entry.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts)


def _infer_autonomy(entries: list[dict[str, Any]]) -> str:
    tool_events = 0
    for entry in entries:
        event_type = str(entry.get("event_type", "")).lower()
        action = str(entry.get("action", "")).lower()
        if event_type in _AUTONOMOUS_SIGNAL_EVENT_TYPES or action in _AUTONOMOUS_SIGNAL_ACTIONS:
            return "autonomous"
        if event_type in _TOOL_EVENT_TYPES:
            tool_events += 1
    if tool_events >= 10:
        return "autonomous"
    if tool_events >= 1:
        return "supervised"
    return "assistive"


def _infer_customer_facing(entries: list[dict[str, Any]]) -> bool:
    return any(
        hint in _entry_text(entry).lower()
        for entry in entries
        for hint in _CUSTOMER_FACING_HINTS
    )


def _infer_data_categories(entries: list[dict[str, Any]]) -> list[str]:
    categories: set[str] = set()
    for entry in entries:
        categories.update(scan_data_categories_from_text(_entry_text(entry)))
    return sorted(categories)


def build_profile_from_agt_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a WorkloadProfileScan-compatible payload from AGT audit entries.

    AGT's AuditEntry schema carries no model/provider/orchestration-framework
    field, so those three signals are left empty rather than guessed.
    """
    agent_ids = {entry["agent_did"] for entry in entries if entry.get("agent_did")}

    return {
        "source": "sdk_scan",
        "models": [],
        "providers": [],
        "frameworks": [],
        "data_categories": _infer_data_categories(entries),
        "deployment_regions": ["us"],
        "agent_count": len(agent_ids),
        "autonomy_level": _infer_autonomy(entries),
        "customer_facing": _infer_customer_facing(entries),
    }
