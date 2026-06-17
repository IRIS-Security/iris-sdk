"""Cost MCP tools (Pro)."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from iris_core.entitlements import Feature
from iris_core.cost.tracker import discover_agent_trackers
from iris_cli.cost import _format_usd, _since_from_date, _suggest_optimizations
from iris_mcp.tools._common import format_table, pro_gate, text_response


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_cost_report",
            description=(
                "Show detailed LLM token cost report for one or all agents."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                    "days": {"type": "integer", "default": 30},
                },
            },
        ),
        Tool(
            name="iris_cost_summary",
            description="Organization-wide cost summary across all agents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "default": 30},
                },
            },
        ),
        Tool(
            name="iris_cost_optimize",
            description=(
                "Suggest cost optimizations for an agent without modifying code."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                    "days": {"type": "integer", "default": 30},
                },
                "required": ["agent_name"],
            },
        ),
    ]


def _pro_required() -> str | None:
    return pro_gate(
        Feature.COST_ORG_SUMMARY,
        "Cost tools require IRIS Pro.\n"
        "Track and optimize LLM spend per agent, tool, and model.\n"
        "iris license activate <your-key> to unlock.",
    )


def _resolve_trackers(agent_name: str | None):
    trackers = list(discover_agent_trackers())
    if not agent_name:
        return trackers
    return [t for t in trackers if t.agent_name == agent_name or t.agent_id == agent_name]


async def report(arguments: dict[str, Any]):
    blocked = _pro_required()
    if blocked:
        return text_response(blocked)

    days = int(arguments.get("days", 30))
    since = _since_from_date(None, days)
    trackers = _resolve_trackers(arguments.get("agent_name"))
    if not trackers:
        return text_response("No cost data found. Govern agents with IRIS SDK integrations first.")

    sections: list[str] = []
    for tracker in trackers:
        summary = tracker.get_summary(since=since)
        sections.append(f"Cost Report — {summary.agent_name} (last {days} days)")
        sections.append(f"Total spend: {_format_usd(summary.total_cost_usd)}")
        sections.append(f"Total calls: {summary.total_calls:,}")
        sections.append(f"Avg per call: {_format_usd(summary.avg_cost_per_call)}")
        sections.append(f"Est. monthly: {_format_usd(summary.estimated_monthly_cost)}")
        if summary.cost_by_model:
            rows = [[m, _format_usd(c)] for m, c in sorted(summary.cost_by_model.items(), key=lambda x: -x[1])]
            sections.append(format_table(["Model", "Cost"], rows[:10]))
        sections.append("")
    return text_response("\n".join(sections).strip())


async def summary(arguments: dict[str, Any]):
    blocked = _pro_required()
    if blocked:
        return text_response(blocked)

    days = int(arguments.get("days", 30))
    since = _since_from_date(None, days)
    trackers = _resolve_trackers(None)
    total = 0.0
    rows = []
    for tracker in trackers:
        s = tracker.get_summary(since=since)
        total += s.total_cost_usd
        rows.append([s.agent_name, _format_usd(s.total_cost_usd), str(s.total_calls), _format_usd(s.estimated_monthly_cost)])

    if not rows:
        return text_response("No cost data found.")

    return text_response(
        f"IRIS Cost Summary (last {days} days)\n"
        f"Total spend: {_format_usd(total)}\n\n"
        + format_table(["Agent", "Spend", "Calls", "Est. monthly"], rows)
    )


async def optimize(arguments: dict[str, Any]):
    blocked = _pro_required()
    if blocked:
        return text_response(blocked)

    agent = arguments["agent_name"]
    days = int(arguments.get("days", 30))
    since = _since_from_date(None, days)
    trackers = _resolve_trackers(agent)
    if not trackers:
        return text_response(f"No cost data found for agent '{agent}'.")

    summary = trackers[0].get_summary(since=since)
    suggestions = _suggest_optimizations(summary, since)
    if not suggestions:
        return text_response(f"No optimization opportunities for {agent}.")
    return text_response(
        f"Cost Optimization — {summary.agent_name}\n\n" + "\n\n".join(suggestions)
    )
