"""Discovery MCP tools — scan, govern, inventory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.types import Tool

from iris import AgentPassport
from iris_core.discovery.scanner import CodebaseScanner
from iris_cli.action_plan import compliance_score
from iris_cli.scan_govern import _detect_change, _unique_files
from iris_mcp.tools._common import format_table, governance_dir, scan_directory, text_response


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_scan_discover",
            description=(
                "Scan a directory for ungoverned AI agents. "
                "Use this when the developer asks what AI agents exist in "
                "their codebase or wants to know what needs to be governed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Path to scan (default: current directory)",
                    },
                },
            },
        ),
        Tool(
            name="iris_scan_govern",
            description=(
                "Show the exact one-line fix for each ungoverned agent found "
                "in the codebase."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Path to scan"},
                    "auto_apply": {
                        "type": "boolean",
                        "description": "Apply fixes to source files",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="iris_list_agents",
            description=(
                "List all agents registered in IRIS with their compliance "
                "scores and current status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "governance_dir": {
                        "type": "string",
                        "description": "Optional path to governance directory",
                    },
                },
            },
        ),
    ]


async def scan_discover(arguments: dict[str, Any]):
    scan_dir = scan_directory(arguments)
    scanner = CodebaseScanner()
    result = scanner.scan_directory(scan_dir)

    lines = [
        "IRIS Discovery Scan",
        f"Directory: {scan_dir}",
        f"Files scanned: {result.files_scanned:,}",
        f"Governed agents: {len(result.governed_agents)}",
        f"Ungoverned findings: {len(result.ungoverned_findings)}",
        "",
    ]

    if result.governed_agents:
        lines.append("Registered agents:")
        for passport in result.governed_agents:
            lines.append(f"  • {passport.name}")
        lines.append("")

    if not result.ungoverned_findings:
        lines.append("✓ No ungoverned AI agent patterns found.")
        return text_response("\n".join(lines))

    rows: list[list[str]] = []
    for finding in result.ungoverned_findings:
        rows.append(
            [
                finding.file_path,
                str(finding.line_number),
                finding.risk_level,
                finding.pattern_matched,
                finding.suggested_command,
            ]
        )
    lines.append("Ungoverned findings:")
    lines.append(
        format_table(
            ["File", "Line", "Risk", "Pattern", "Fix command"],
            rows,
        )
    )
    lines.append("")
    lines.append(
        "Next: call iris_scan_govern to see exact code changes, "
        "or iris_declare to register a new agent."
    )
    return text_response("\n".join(lines))


async def scan_govern(arguments: dict[str, Any]):
    scan_dir = scan_directory(arguments)
    auto_apply = bool(arguments.get("auto_apply", False))
    scanner = CodebaseScanner()
    result = scanner.scan_directory(scan_dir)
    unique = _unique_files(result.ungoverned_findings)

    if not unique:
        return text_response("✓ No ungoverned agents found — nothing to govern.")

    owner = "platform-team@company.com"
    lines = [
        f"IRIS Govern — {len(unique)} ungoverned agent(s)",
        f"Directory: {scan_dir}",
        "",
    ]

    for finding in unique:
        change = _detect_change(finding, scan_dir, owner)
        if not change:
            lines.append(f"⚠ Could not generate fix for {finding.file_path}")
            continue

        lines.append(f"File: {change.file_path}")
        lines.append(f"Agent: {change.agent_name}")
        lines.append(f"Framework: {change.framework}")
        lines.append("")
        lines.append(f"- {change.original_line.strip()}")
        for imp in change.imports:
            lines.append(f"+ {imp}")
        for pline in change.passport_lines:
            lines.append(f"+ {pline}")
        lines.append(f"+ {change.replacement_line}")
        lines.append("")

        if auto_apply:
            from iris_cli.scan_govern import _apply_change

            _apply_change(change)
            lines.append(f"✓ Applied changes to {change.file_path}")
            lines.append("")

    if not auto_apply:
        lines.append(
            "To apply these changes, re-run with auto_apply: true "
            "or use the suggested iris register commands."
        )

    return text_response("\n".join(lines))


async def list_agents(arguments: dict[str, Any]):
    gov_dir = governance_dir(arguments)
    if not gov_dir.exists():
        return text_response(
            f"No governance directory found at {gov_dir}.\n"
            "Run iris_scan_discover to find agents, then iris_declare to register."
        )

    rows: list[list[str]] = []
    for passport_file in sorted(gov_dir.rglob("passport.yaml")):
        try:
            passport = AgentPassport.from_yaml(passport_file.read_text())
        except Exception:
            continue
        agent_dir = passport_file.parent
        score = compliance_score(passport, agent_dir, "colorado-ai-act")
        has_policy = (agent_dir / "policy.cedar").exists()
        has_assessment = (agent_dir / "impact-assessment.md").exists()
        if score >= 1.0 and has_policy:
            status = "PROD READY"
        elif has_policy:
            status = "IN PROGRESS"
        else:
            status = "NEEDS POLICY"
        next_action = "iris compile policy" if not has_policy else (
            "iris compliance assess" if not has_assessment else "iris compliance check"
        )
        rows.append(
            [
                passport.name,
                f"{int(score * 100)}%",
                status,
                next_action,
            ]
        )

    if not rows:
        return text_response(f"No agents registered under {gov_dir}.")

    body = format_table(["Agent", "Score", "Status", "Next action"], rows)
    return text_response(f"IRIS Agent Inventory ({gov_dir})\n\n{body}")
