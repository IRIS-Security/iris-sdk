"""Monitoring MCP tools — status, witness, sentinel, drift."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.types import Tool

from iris import AgentPassport
from iris_core.cost.tracker import discover_agent_trackers
from iris_core.discovery.scanner import CodebaseScanner
from iris_core.drift.detector import DriftDetector
from iris_core.entitlements import Feature
from iris_cli.action_plan import compliance_score
from iris_cli.witness import _format_witness_event
from iris_mcp.tools._common import format_table, governance_dir, pro_gate, text_response


def get_free_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_status",
            description=(
                "Show compliance dashboard for all governed agents — scores, "
                "status, and next actions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                    "governance_dir": {"type": "string"},
                },
            },
        ),
        Tool(
            name="iris_witness_recent",
            description=(
                "Show recent policy decisions from the Evidence Vault witness feed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["agent_name"],
            },
        ),
    ]


def get_pro_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_sentinel_status",
            description=(
                "One-shot sentinel check — drift, violations, and cost snapshot."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "governance_dir": {"type": "string"},
                },
            },
        ),
        Tool(
            name="iris_drift_check",
            description=(
                "Check for compliance posture drift since the last snapshot."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "governance_dir": {"type": "string"},
                },
            },
        ),
    ]


def _next_action(passport: AgentPassport, agent_dir: Path) -> str:
    if not (agent_dir / "policy.cedar").exists():
        return f"iris_compile_policy agent_name={passport.name}"
    if not (agent_dir / "impact-assessment.md").exists():
        return f"iris_compliance_assess agent_name={passport.name}"
    return f"iris_compliance_check framework=colorado-ai-act agent_name={passport.name}"


async def status(arguments: dict[str, Any]):
    gov_dir = governance_dir(arguments)
    agent_filter = arguments.get("agent_name")
    rows: list[list[str]] = []

    for passport_file in sorted(gov_dir.rglob("passport.yaml")):
        try:
            passport = AgentPassport.from_yaml(passport_file.read_text())
        except Exception:
            continue
        if agent_filter and passport.name != agent_filter:
            continue
        agent_dir = passport_file.parent
        score = compliance_score(passport, agent_dir, "colorado-ai-act")
        label = "READY" if score >= 1.0 else f"{int((1 - score) * 10)} actions"
        rows.append([passport.name, f"{int(score * 100)}%", label, _next_action(passport, agent_dir)])

    if not rows:
        return text_response("No governed agents found.")

    return text_response(
        "IRIS Status Dashboard\n\n"
        + format_table(["Agent", "Score", "Status", "Next action"], rows)
    )


async def witness_recent(arguments: dict[str, Any]):
    agent = arguments["agent_name"]
    limit = int(arguments.get("limit", 20))
    vault_root = Path.home() / ".iris" / "evidence" / agent / "events.jsonl"
    if not vault_root.exists():
        return text_response(f"No witness events yet for {agent}.")

    lines = [f"IRIS Witness — last {limit} events for {agent}", ""]
    raw_lines = vault_root.read_text(encoding="utf-8").strip().splitlines()
    for raw in raw_lines[-limit:]:
        try:
            event = json.loads(raw)
            lines.append(_format_witness_event(event, agent))
        except json.JSONDecodeError:
            continue
    return text_response("\n".join(lines))


async def sentinel_status(arguments: dict[str, Any]):
    blocked = pro_gate(
        Feature.DRIFT_SLACK_ALERT,
        "iris sentinel status requires IRIS Pro.\n"
        "iris license activate <your-key> to unlock.",
    )
    if blocked:
        return text_response(blocked)

    gov = governance_dir(arguments)
    detector = DriftDetector(gov)
    if not detector.list_snapshots():
        detector.take_snapshot()

    report = detector.detect_drift()
    governed = len(list(gov.rglob("passport.yaml"))) if gov.exists() else 0
    violations = len(report.new_violations)
    cost = sum(t.get_summary().estimated_monthly_cost for t in discover_agent_trackers())
    scanner = CodebaseScanner()
    discover = scanner.scan_directory(Path.cwd())

    ts = datetime.now().strftime("%H:%M:%S")
    lines = [
        f"[{ts}] IRIS Sentinel Status",
        f"Agents governed: {governed}",
        f"New violations: {violations}",
        f"Estimated monthly LLM cost: ${cost:.2f}",
        f"Ungoverned files in cwd: {len(discover.ungoverned_findings)}",
        "",
        report.summary,
    ]
    for change in report.score_changes:
        if change.direction == "degraded":
            lines.append(
                f"ALERT — {change.agent_name} score dropped "
                f"{int(change.previous_score * 100)}%→{int(change.current_score * 100)}%"
            )
    return text_response("\n".join(lines))


async def drift_check(arguments: dict[str, Any]):
    blocked = pro_gate(
        Feature.DRIFT_SLACK_ALERT,
        "iris drift check requires IRIS Pro.\n"
        "iris license activate <your-key> to unlock.",
    )
    if blocked:
        return text_response(blocked)

    gov = governance_dir(arguments)
    detector = DriftDetector(gov)
    if not detector.list_snapshots():
        detector.take_snapshot()
        return text_response("Initial drift baseline saved. Re-run after making changes.")

    report = detector.detect_drift()
    rows: list[list[str]] = []
    for event in report.new_violations:
        rows.append(["NEW", event.agent_name, f"{event.rule_id}: {event.description}"])
    for event in report.resolved_violations:
        rows.append(["RESOLVED", event.agent_name, f"{event.rule_id}: {event.description}"])
    for change in report.score_changes:
        rows.append(
            [
                f"SCORE {change.direction}",
                change.agent_name,
                f"{change.framework}: {int(change.previous_score * 100)}% → "
                f"{int(change.current_score * 100)}%",
            ]
        )

    if not rows:
        return text_response(f"No drift detected.\n{report.summary}")

    return text_response(
        f"Compliance Drift Check\n\n{format_table(['Change', 'Agent', 'Detail'], rows)}\n\n"
        f"{report.summary}"
    )
