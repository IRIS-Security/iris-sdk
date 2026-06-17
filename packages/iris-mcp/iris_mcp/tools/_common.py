"""Shared helpers for IRIS MCP tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.types import TextContent

from iris_core.entitlements import Entitlements, Feature


def text_response(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def scan_directory(arguments: dict[str, Any]) -> Path:
    directory = arguments.get("directory")
    if directory:
        return Path(directory).expanduser().resolve()
    return Path.cwd()


def governance_dir(arguments: dict[str, Any] | None = None) -> Path:
    arguments = arguments or {}
    if arguments.get("governance_dir"):
        return Path(arguments["governance_dir"]).expanduser().resolve()

    env_dir = os.environ.get("IRIS_GOVERNANCE_DIR")
    if env_dir:
        path = Path(env_dir).expanduser().resolve()
        if path.name == "agents":
            return path
        agents = path / "agents"
        if agents.exists():
            return agents
        return path

    return Path.cwd() / "governance" / "agents"


def has_pro() -> bool:
    return Entitlements().has(Feature.BUNDLE_HIPAA)


def pro_gate(feature: Feature, upgrade_message: str) -> str | None:
    if Entitlements().has(feature):
        return None
    return upgrade_message


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "No results."
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    sep = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    lines = [sep, "-" * len(sep)]
    for row in rows:
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(lines)
