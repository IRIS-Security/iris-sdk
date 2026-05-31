"""Filter OpenAI tools[] to passport-declared permissions."""

from __future__ import annotations

import logging
import sys
from typing import Any, List, Optional

from iris_core.models.passport import AgentPassport, Environment
from iris_core.models.policy import Severity, Violation

from iris_openai._governance import current_environment

logger = logging.getLogger("iris.openai.tools")


def _tool_name(tool: Any) -> Optional[str]:
    if not isinstance(tool, dict):
        return getattr(tool, "name", None)
    if tool.get("type") == "function":
        fn = tool.get("function") or {}
        return fn.get("name")
    return tool.get("name")


def _log_tool_removal(violation: Violation) -> None:
    msg = (
        f"[IRIS TOOL FILTER] {violation.message} "
        f"Remediation: {violation.remediation}"
    )
    logger.warning(msg)
    # Always emit to stderr so removals are never silent (required in dev; auditable in prod).
    print(msg, file=sys.stderr)


def guard_openai_tools(
    tools: List[Any],
    passport: AgentPassport,
    environment: Optional[Environment] = None,
) -> List[Any]:
    """
    Return only tools permitted by passport.tool_permissions.

    Removed tools are logged as IRIS-TOOL-001 violations. In dev/test, removal
    is never silent — every dropped tool is logged with a reason. In production
    with no tool_permissions declared, all tools are removed.
    """
    if not tools:
        return []

    env = environment or current_environment()
    allowed = {t.tool_id for t in passport.tool_permissions}
    filtered: List[Any] = []

    if env == Environment.PRODUCTION and not allowed:
        for tool in tools:
            name = _tool_name(tool) or "unknown"
            violation = Violation(
                rule_id="IRIS-TOOL-001",
                severity=Severity.CRITICAL,
                message=(
                    f"Tool '{name}' removed: agent '{passport.name}' has no "
                    f"tool_permissions — all tools are blocked in production."
                ),
                compliance_refs=["iris:tool-permission"],
                remediation=(
                    "Add tool_permissions to the agent passport before using tools "
                    "in production."
                ),
            )
            _log_tool_removal(violation)
        return []

    for tool in tools:
        name = _tool_name(tool)
        if not name:
            filtered.append(tool)
            continue
        if name in allowed:
            filtered.append(tool)
            continue
        violation = Violation(
            rule_id="IRIS-TOOL-001",
            severity=Severity.HIGH,
            message=(
                f"Tool '{name}' removed: not in agent '{passport.name}' "
                f"tool_permissions. Allowed: {sorted(allowed) or ['none declared']}."
            ),
            compliance_refs=["iris:tool-permission", "colorado-ai-act:transparency"],
            remediation=(
                f"Add '{name}' to tool_permissions in passport.yaml and obtain "
                f"security engineer approval."
            ),
        )
        _log_tool_removal(violation)

    return filtered
