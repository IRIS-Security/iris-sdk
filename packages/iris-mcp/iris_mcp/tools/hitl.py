"""HITL MCP tools (Pro)."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from mcp.types import Tool

from iris_core.entitlements import Feature
from iris_core.hitl.models import HITLStatus
from iris_core.hitl.queue import HITLQueue
from iris_mcp.tools._common import format_table, pro_gate, text_response


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_hitl_list",
            description=(
                "Show all pending human review requests. Call this when the "
                "developer asks what needs their approval or when an agent call "
                "was paused waiting for a human decision."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                },
            },
        ),
        Tool(
            name="iris_hitl_approve",
            description=(
                "Approve a pending human review request, allowing the paused "
                "agent call to proceed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "review_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["review_id"],
            },
        ),
        Tool(
            name="iris_hitl_reject",
            description=(
                "Reject a pending human review request, blocking the agent call."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "review_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["review_id", "reason"],
            },
        ),
        Tool(
            name="iris_hitl_rules",
            description="Show what will and will not trigger HITL for an agent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                },
                "required": ["agent_name"],
            },
        ),
    ]


def _pro_required() -> str | None:
    return pro_gate(
        Feature.HITL_GATE,
        "HITL tools require IRIS Pro.\n"
        "Human-in-the-loop approval gates sensitive agent actions.\n"
        "iris license activate <your-key> to unlock.",
    )


def _time_remaining(expires_at: str) -> str:
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", ""))
        delta = expiry - datetime.utcnow()
        seconds = int(delta.total_seconds())
        if seconds <= 0:
            return "expired"
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}m {secs}s"
    except ValueError:
        return "unknown"


async def list_reviews(arguments: dict[str, Any]):
    blocked = _pro_required()
    if blocked:
        return text_response(blocked)

    queue = HITLQueue()
    reviews = queue.list_pending(agent_name=arguments.get("agent_name"))
    if not reviews:
        return text_response("No pending HITL reviews.")

    rows = []
    for review in reviews:
        rows.append(
            [
                review.review_id[:14],
                review.agent_name,
                review.risk_level,
                f"{review.tool_name}/{review.action}",
                _time_remaining(review.expires_at),
            ]
        )
    return text_response(
        f"{len(reviews)} pending review(s)\n\n"
        + format_table(["ID", "Agent", "Risk", "Action", "Expires"], rows)
    )


async def approve(arguments: dict[str, Any]):
    blocked = _pro_required()
    if blocked:
        return text_response(blocked)

    queue = HITLQueue()
    reviewer = os.environ.get("IRIS_USER_EMAIL", "local-reviewer")
    review = queue.resolve(
        arguments["review_id"],
        HITLStatus.APPROVED,
        reviewer,
        reviewer_note=arguments.get("note"),
    )
    token_line = ""
    if review.approval_token:
        token_line = f"\nApproval token: {review.approval_token[:32]}..."
    return text_response(
        f"✓ Review {arguments['review_id']} approved by {reviewer}{token_line}\n"
        "Logged to Evidence Vault. The waiting agent call will now proceed."
    )


async def reject(arguments: dict[str, Any]):
    blocked = _pro_required()
    if blocked:
        return text_response(blocked)

    queue = HITLQueue()
    reviewer = os.environ.get("IRIS_USER_EMAIL", "local-reviewer")
    queue.resolve(
        arguments["review_id"],
        HITLStatus.REJECTED,
        reviewer,
        reviewer_note=arguments.get("reason"),
    )
    return text_response(
        f"✗ Review {arguments['review_id']} rejected by {reviewer}\n"
        f"Reason: {arguments.get('reason', '')}\n"
        "The waiting agent call will raise IrisViolationError."
    )


async def show_rules(arguments: dict[str, Any]):
    blocked = _pro_required()
    if blocked:
        return text_response(blocked)

    from iris_cli.hitl import _load_passport, _parse_cedar_hitl_annotations

    agent = arguments["agent_name"]
    passport = _load_passport(agent)
    config = passport.hitl_config
    lines = [f"HITL Rules — {agent}", ""]
    if config and config.condition_rules:
        lines.append(f"Declared condition rules ({len(config.condition_rules)}):")
        for rule in config.condition_rules:
            lines.append(f"  • {rule.condition} — {rule.reason}")
    cedar = _parse_cedar_hitl_annotations(passport)
    if cedar:
        lines.append(f"Cedar HITL annotations ({len(cedar)}):")
        for entry in cedar:
            lines.append(f"  • {entry['summary']}")
    lines.append("")
    lines.append("Everything else proceeds automatically without HITL.")
    return text_response("\n".join(lines))
