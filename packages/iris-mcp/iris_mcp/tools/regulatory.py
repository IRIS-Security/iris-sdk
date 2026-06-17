"""Regulatory MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.types import Tool

from iris_core.regulatory.tracker import RegulatoryTracker
from iris_mcp.tools._common import governance_dir, text_response


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_regulatory_check",
            description=(
                "Check for regulatory updates affecting your active compliance "
                "frameworks. Call when the developer asks about AI law changes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "framework": {"type": "string"},
                    "governance_dir": {"type": "string"},
                    "offline": {"type": "boolean", "default": True},
                },
            },
        ),
    ]


def _collect_frameworks(gov_dir: Path, framework: str | None) -> list[str]:
    if framework:
        return [framework]

    from iris import AgentPassport

    frameworks: set[str] = set()
    if gov_dir.exists():
        for passport_file in gov_dir.rglob("passport.yaml"):
            try:
                passport = AgentPassport.from_yaml(passport_file.read_text(encoding="utf-8"))
                for tag in passport.compliance_tags or []:
                    value = tag.value if hasattr(tag, "value") else str(tag)
                    frameworks.add(value)
            except Exception:
                continue
    return sorted(frameworks) or ["colorado-ai-act"]


async def check(arguments: dict[str, Any]):
    gov_dir = governance_dir(arguments)
    frameworks = _collect_frameworks(gov_dir, arguments.get("framework"))
    offline = bool(arguments.get("offline", True))
    tracker = RegulatoryTracker()
    updates = tracker.check_for_updates(frameworks, use_remote=not offline)

    lines = [
        "Regulatory Intelligence Check",
        f"Frameworks checked: {', '.join(frameworks)}",
        f"Last registry update: {tracker.last_updated or 'bundled'}",
        "",
    ]

    if updates:
        lines.append("UPDATES AVAILABLE:")
        for update in updates:
            if update.is_new_bundle:
                lines.append(f"  NEW {update.bundle_id}: {update.change_summary}")
            else:
                lines.append(
                    f"  {update.change_severity} {update.bundle_id}: "
                    f"v{update.current_installed_version} → v{update.available_version}"
                )
                lines.append(f"    {update.change_summary}")
        lines.append("")
        lines.append("Review policy-intent.md and re-run iris_compliance_check.")
    else:
        lines.append("✓ All checked frameworks are up to date.")

    return text_response("\n".join(lines))
