"""Evidence MCP tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.types import Tool

from iris_core.entitlements import Feature
from iris_core.evidence.vault import EvidenceVault
from iris_cli.evidence import aggregate_stats, build_report_data, format_report_markdown
from iris_mcp.tools._common import governance_dir, pro_gate, text_response


def _load_passport(agent: str, gov_dir: Path):
    from iris import AgentPassport

    passport_file = gov_dir / agent / "passport.yaml"
    if not passport_file.exists():
        raise FileNotFoundError(f"No passport for agent '{agent}'")
    return AgentPassport.from_yaml(passport_file.read_text())


def get_free_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_evidence_summary",
            description=(
                "Summarize Evidence Vault activity across all governed agents."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "governance_dir": {"type": "string"},
                },
            },
        ),
    ]


def get_pro_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_evidence_report",
            description=(
                "Generate a complete audit report for an agent from the Evidence Vault."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                    "since": {"type": "string"},
                },
                "required": ["agent_name"],
            },
        ),
        Tool(
            name="iris_evidence_export",
            description=(
                "Export the full Evidence Vault for an agent to a file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                    "output_path": {"type": "string"},
                    "format": {"type": "string", "enum": ["json", "csv"], "default": "json"},
                },
                "required": ["agent_name", "output_path"],
            },
        ),
    ]


async def summary(arguments: dict[str, Any]):
    gov_dir = governance_dir(arguments)
    if not gov_dir.exists():
        return text_response("No governed agents — Evidence Vault is empty.")

    stats = aggregate_stats(gov_dir)
    lines = [
        "IRIS Evidence Vault Summary",
        f"Agents: {stats['total_agents']}",
        f"Evaluations this week: {stats['total_evaluations_this_week']}",
        "",
    ]
    if stats["top_violated_rules"]:
        lines.append("Top violated rules:")
        for entry in stats["top_violated_rules"]:
            lines.append(f"  • {entry['rule_id']}: {entry['count']} times")
    if stats["agents_approaching_review"]:
        lines.append("")
        lines.append("Annual reviews due:")
        for entry in stats["agents_approaching_review"]:
            lines.append(f"  • {entry['agent']}: {entry['status']}")
    return text_response("\n".join(lines))


async def report(arguments: dict[str, Any]):
    blocked = pro_gate(
        Feature.VAULT_PDF_EXPORT,
        "iris evidence report requires IRIS Pro for full audit reports.\n"
        "iris license activate <your-key> to unlock.",
    )
    if blocked:
        return text_response(blocked)

    agent = arguments["agent_name"]
    gov_dir = governance_dir(arguments)
    try:
        passport = _load_passport(agent, gov_dir)
    except FileNotFoundError as exc:
        return text_response(str(exc))

    vault = EvidenceVault(agent_id=agent)
    data = build_report_data(agent, passport, vault, since=arguments.get("since"))
    return text_response(format_report_markdown(data))


async def export(arguments: dict[str, Any]):
    blocked = pro_gate(
        Feature.EVIDENCE_EXPORT_CSV,
        "iris evidence export requires IRIS Pro.\n"
        "iris license activate <your-key> to unlock.",
    )
    if blocked:
        return text_response(blocked)

    agent = arguments["agent_name"]
    output_path = Path(arguments["output_path"]).expanduser()
    output_format = arguments.get("format", "json")
    gov_dir = governance_dir(arguments)

    try:
        passport = _load_passport(agent, gov_dir)
    except FileNotFoundError as exc:
        return text_response(str(exc))

    vault = EvidenceVault(agent_id=agent)
    vault_data = vault.export_vault()
    vault_data["passport"] = {
        "owner": passport.owner,
        "team": passport.team,
        "evidence_vault_id": passport.evidence_vault_id,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        output_path.write_text(json.dumps(vault_data, indent=2))
    else:
        from iris_cli.evidence import _export_csv

        _export_csv(vault_data, output_path)

    return text_response(f"✓ Evidence exported to {output_path}")
