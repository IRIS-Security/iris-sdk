"""Strict payload schemas for EvidenceEvent types."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Mapping

PAYLOAD_SCHEMAS: Dict[str, FrozenSet[str]] = {
    "cedar_decision": frozenset(
        {
            "rule_id",
            "framework",
            "action",
            "tool_name",
            "data_classification",
            "user_id_hash",
        }
    ),
    "hitl_requested": frozenset(
        {
            "review_id",
            "triggered_by",
            "rule_or_condition",
            "timeout_seconds",
            "notify_channels",
        }
    ),
    "hitl_resolved": frozenset(
        {
            "review_id",
            "status",
            "resolved_by",
            "reviewer_note",
            "approval_token",
            "resolution_time_seconds",
        }
    ),
    "dlp_finding": frozenset(
        {"finding_type", "severity", "action_taken", "location"}
    ),
    "drift_detected": frozenset(
        {"baseline_score", "current_score", "delta", "affected_rules"}
    ),
    "agent_registered": frozenset(
        {"owner", "team", "compliance_tags", "is_high_risk"}
    ),
    "policy_compiled": frozenset(
        {"intent_hash", "cedar_policy_hash", "compiled_by", "git_commit_sha"}
    ),
    "rotation_event": frozenset(
        {"key_name", "provider", "old_version", "new_version", "rotation_method"}
    ),
    "org_policy_changed": frozenset(
        {"policy_repo", "commit_sha", "changed_by", "diff_summary"}
    ),
    "cicd_run": frozenset(
        {"system", "run_id", "pipeline_url", "triggered_by", "outcome"}
    ),
    "org_discovery_scan": frozenset(
        {
            "org_id",
            "scan_id",
            "started_at",
            "completed_at",
            "sources_scanned",
            "total_agents",
            "governed_count",
            "ungoverned_count",
            "by_framework",
            "by_source_type",
            "status",
            "agents",
        }
    ),
    "event_expired": frozenset(
        {"original_event_id", "original_event_type", "expired_at", "reason"}
    ),
    "vault_rate_limited": frozenset(
        {"limit_per_minute", "attempted_event_type", "client_id"}
    ),
    "retention_extended": frozenset({"event_id", "reason", "hold_until"}),
}


class PayloadSchemaError(ValueError):
    """Raised when an event payload violates its schema."""


def validate_payload(event_type: str, payload: Mapping[str, Any]) -> dict:
    """Validate payload fields strictly; reject unknown keys."""
    allowed = PAYLOAD_SCHEMAS.get(event_type)
    if allowed is None:
        raise PayloadSchemaError(f"Unknown event_type: {event_type}")

    keys = set(payload.keys())
    unknown = keys - allowed
    if unknown:
        raise PayloadSchemaError(
            f"Unknown fields for {event_type}: {sorted(unknown)}"
        )
    missing = allowed - keys
    if missing:
        raise PayloadSchemaError(
            f"Missing required fields for {event_type}: {sorted(missing)}"
        )
    return dict(payload)
