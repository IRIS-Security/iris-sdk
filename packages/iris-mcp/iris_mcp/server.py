"""IRIS MCP Server — connect Claude Desktop and Cursor to AI governance."""

from __future__ import annotations

import argparse
import asyncio
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import GetPromptResult, Prompt, PromptMessage, Resource, TextContent, TextResourceContents

from iris_core.entitlements import Entitlements, Feature
from iris_mcp import __version__
from iris_mcp.prompts.system import IRIS_SYSTEM_PROMPT
from iris_mcp.resources.frameworks import FRAMEWORK_RESOURCES, get_framework_text
from iris_mcp.tools import (
    compliance,
    cost,
    discovery,
    evidence,
    governance,
    hitl,
    monitoring,
    regulatory,
)

app = Server("iris-governance")


def collect_tools(*, include_pro: bool | None = None) -> list:
    if include_pro is None:
        include_pro = Entitlements().has(Feature.BUNDLE_HIPAA)

    tools = []
    tools.extend(discovery.get_tools())
    tools.extend(compliance.get_free_tools())
    tools.extend(governance.get_tools())
    tools.extend(monitoring.get_free_tools())
    tools.extend(evidence.get_free_tools())
    tools.extend(regulatory.get_tools())

    if include_pro:
        tools.extend(compliance.get_pro_tools())
        tools.extend(evidence.get_pro_tools())
        tools.extend(hitl.get_tools())
        tools.extend(cost.get_tools())
        tools.extend(monitoring.get_pro_tools())

    return tools


@app.list_tools()
async def list_tools() -> list:
    """Return all available IRIS tools."""
    return collect_tools()


@app.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    """Route tool calls to the appropriate handler."""
    arguments = arguments or {}
    router = {
        "iris_scan_discover": discovery.scan_discover,
        "iris_scan_govern": discovery.scan_govern,
        "iris_list_agents": discovery.list_agents,
        "iris_compliance_check": compliance.check,
        "iris_framework_suggest": compliance.framework_suggest,
        "iris_regulatory_check": regulatory.check,
        "iris_compliance_assess": compliance.assess,
        "iris_certify": compliance.certify,
        "iris_policy_catalog": compliance.catalog,
        "iris_declare": governance.declare,
        "iris_compile_policy": governance.compile,
        "iris_preview_policy": governance.preview,
        "iris_status": monitoring.status,
        "iris_witness_recent": monitoring.witness_recent,
        "iris_sentinel_status": monitoring.sentinel_status,
        "iris_drift_check": monitoring.drift_check,
        "iris_evidence_summary": evidence.summary,
        "iris_evidence_report": evidence.report,
        "iris_evidence_export": evidence.export,
        "iris_hitl_list": hitl.list_reviews,
        "iris_hitl_approve": hitl.approve,
        "iris_hitl_reject": hitl.reject,
        "iris_hitl_rules": hitl.show_rules,
        "iris_cost_report": cost.report,
        "iris_cost_summary": cost.summary,
        "iris_cost_optimize": cost.optimize,
    }

    handler = router.get(name)
    if not handler:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return await handler(arguments)


@app.list_resources()
async def list_resources() -> list[Resource]:
    """Return framework documentation as readable resources."""
    return FRAMEWORK_RESOURCES


@app.read_resource()
async def read_resource(uri: str) -> str:
    text = get_framework_text(str(uri))
    if text is None:
        raise ValueError(f"Unknown resource: {uri}")
    return text


@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    """Return pre-built prompts for common IRIS tasks."""
    return [
        Prompt(
            name="govern_new_agent",
            description="Walk through governing a new AI agent from scratch",
            arguments=[
                {"name": "agent_name", "description": "Name of the agent", "required": True},
                {"name": "domain", "description": "What the agent does", "required": True},
            ],
        ),
        Prompt(
            name="compliance_review",
            description="Run a full compliance review for an agent",
            arguments=[
                {"name": "agent_name", "description": "Agent to review", "required": True},
            ],
        ),
        Prompt(
            name="explain_framework",
            description="Explain a compliance framework in plain English",
            arguments=[
                {"name": "framework", "description": "Framework ID", "required": True},
            ],
        ),
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    arguments = arguments or {}
    if name == "govern_new_agent":
        agent = arguments.get("agent_name", "my-agent")
        domain = arguments.get("domain", "AI assistant")
        text = (
            f"Help me govern a new AI agent named {agent}.\n"
            f"It does: {domain}\n\n"
            f"Use iris_declare, then iris_compile_policy, then iris_compliance_check."
        )
    elif name == "compliance_review":
        agent = arguments.get("agent_name", "my-agent")
        text = (
            f"Run a full compliance review for agent {agent}.\n"
            "Use iris_status, iris_framework_suggest, iris_compliance_check, "
            "and iris_evidence_summary."
        )
    elif name == "explain_framework":
        framework = arguments.get("framework", "colorado-ai-act")
        text = (
            f"Read iris://frameworks/{framework} and explain it in plain English "
            "for a developer building AI agents."
        )
    else:
        text = IRIS_SYSTEM_PROMPT

    return GetPromptResult(
        description=name,
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
    )


async def run_server() -> None:
    async with stdio_server() as streams:
        await app.run(
            streams[0],
            streams[1],
            app.create_initialization_options(
                instructions=IRIS_SYSTEM_PROMPT,
            ),
        )


def cli_main() -> None:
    parser = argparse.ArgumentParser(description="IRIS MCP Server")
    parser.add_argument("--version", action="version", version=f"iris-mcp {__version__}")
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List available MCP tools and exit",
    )
    parser.add_argument(
        "--cursor-mode",
        action="store_true",
        help="Cursor IDE mode (stdio transport; reserved for future options)",
    )
    args = parser.parse_args()

    if args.list_tools:
        tools = collect_tools()
        for tool in tools:
            tier = "pro" if tool.name in {
                "iris_compliance_assess",
                "iris_certify",
                "iris_policy_catalog",
                "iris_sentinel_status",
                "iris_drift_check",
                "iris_evidence_report",
                "iris_evidence_export",
                "iris_hitl_list",
                "iris_hitl_approve",
                "iris_hitl_reject",
                "iris_hitl_rules",
                "iris_cost_report",
                "iris_cost_summary",
                "iris_cost_optimize",
            } else "free"
            print(f"{tool.name}\t{tier}\t{tool.description}")
        return

    if args.cursor_mode:
        pass

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        sys.exit(0)


def main() -> None:
    cli_main()


if __name__ == "__main__":
    main()
