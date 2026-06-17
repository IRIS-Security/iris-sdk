"""Governance MCP tools — declare, compile, preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.types import Tool

from iris import AgentPassport
from iris_cli.declare import _write_agent_files
from iris_cli.compiler_config import create_policy_compiler
from iris_cli.policy_diff import run_policy_diff
from iris_mcp.tools._common import governance_dir, text_response


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_declare",
            description=(
                "Register a new AI agent with IRIS governance. Creates an AgentPassport "
                "that declares the agent's identity, compliance requirements, and allowed "
                "actions. Call this when the developer wants to start governing a new agent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "owner": {"type": "string"},
                    "team": {"type": "string"},
                    "description": {"type": "string"},
                    "compliance_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "is_high_risk": {"type": "boolean", "default": False},
                },
                "required": ["name", "owner", "team", "description"],
            },
        ),
        Tool(
            name="iris_compile_policy",
            description=(
                "Compile the agent's plain English policy intent into an enforced "
                "Cedar policy. Call this after declaring an agent or after updating "
                "policy-intent.md."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                    "intent": {
                        "type": "string",
                        "description": "Optional plain English policy to compile",
                    },
                },
                "required": ["agent_name"],
            },
        ),
        Tool(
            name="iris_preview_policy",
            description=(
                "Show the risk impact of a policy change before applying it. "
                "Like terraform plan but for AI governance policy."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                },
                "required": ["agent_name"],
            },
        ),
    ]


async def declare(arguments: dict[str, Any]):
    name = arguments["name"]
    owner = arguments["owner"]
    team = arguments["team"]
    description = arguments.get("description", "")
    compliance = arguments.get("compliance_tags") or ["colorado-ai-act"]
    high_risk = bool(arguments.get("is_high_risk", False))
    output = governance_dir(arguments) / name

    _write_agent_files(
        name=name,
        owner=owner,
        team=team,
        env=("dev",),
        high_risk=high_risk,
        compliance_list=list(compliance),
        output=output,
        description=description,
    )

    return text_response(
        f"✓ Agent registered: {name}\n"
        f"Passport: {output / 'passport.yaml'}\n"
        f"Intent template: {output / 'policy-intent.md'}\n\n"
        f"Next steps:\n"
        f"  1. Edit policy-intent.md with what the agent may do\n"
        f"  2. Call iris_compile_policy for agent {name}\n"
        f"  3. Call iris_compliance_check with framework colorado-ai-act"
    )


async def compile(arguments: dict[str, Any]):
    agent = arguments["agent_name"]
    gov_dir = governance_dir(arguments) / agent
    passport_file = gov_dir / "passport.yaml"
    if not passport_file.exists():
        return text_response(f"No passport for '{agent}'. Run iris_declare first.")

    passport = AgentPassport.from_yaml(passport_file.read_text())
    intent_file = gov_dir / "policy-intent.md"
    if arguments.get("intent"):
        intent_file.write_text(arguments["intent"])
    if not intent_file.exists():
        return text_response(f"No policy-intent.md at {intent_file}")

    intent_text = intent_file.read_text()
    compiler = create_policy_compiler()
    result = compiler.compile(intent_text, passport)

    if result.has_blocking_violations():
        lines = ["Policy compilation blocked:", ""]
        for violation in result.violations:
            lines.append(f"✗ {violation.rule_id}: {violation.message}")
            lines.append(f"  Fix: {violation.remediation}")
        return text_response("\n".join(lines))

    cedar_preview = result.cedar_policy[:4000] if result.cedar_policy else "(no output)"
    if not arguments.get("intent"):
        (gov_dir / "policy.cedar").write_text(result.cedar_policy or "")

    return text_response(
        f"✓ Policy compiled for {agent}\n"
        f"Output: {gov_dir / 'policy.cedar'}\n\n"
        f"Cedar preview:\n{cedar_preview}"
    )


async def preview(arguments: dict[str, Any]):
    agent = arguments["agent_name"]
    try:
        result = run_policy_diff(agent, governance_dir=governance_dir(arguments) / agent)
    except Exception as exc:
        return text_response(f"Preview failed: {exc}")

    lines = [f"IRIS Policy Preview — {agent}", f"Comparing: {result.compare_label}", ""]
    for diff in result.diffs:
        if diff.status == "UNCHANGED":
            continue
        label = {"DECREASED": "SAFER", "INCREASED": "RISKIER", "NEUTRAL": "NEUTRAL"}.get(
            diff.risk_delta, "NEUTRAL"
        )
        lines.append(f"CHANGE — {label} ({diff.status})")
        if diff.old_rule:
            lines.append(f"  Before: {diff.old_rule.plain_english}")
        if diff.new_rule:
            lines.append(f"  After:  {diff.new_rule.plain_english}")
        lines.append(f"  Why: {diff.risk_reason}")
        lines.append("")

    if len(lines) <= 3:
        lines.append("No policy changes detected.")
    lines.append(f"Apply: iris_compile_policy with agent_name {agent}")
    return text_response("\n".join(lines))
