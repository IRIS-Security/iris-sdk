"""
IRIS LangChain integration — governance in three lines of code.

Quickstart:
    from iris_langchain import IrisLangChainAgent
    from iris import AgentPassport, ComplianceTag

    passport = AgentPassport(
        name="support-agent",
        owner="team@company.com",
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    )
    agent = IrisLangChainAgent.from_agent(base_agent, passport)
    result = agent.run("Help this customer")
"""

from __future__ import annotations

from iris import IrisViolationError
from iris_core.models.passport import (
    AgentPassport,
    ComplianceTag,
    DataClassification,
    Environment,
    ToolPermission,
)
from iris_core.models.policy import PolicyResult, Severity, Violation

from iris_langchain.agent import IrisLangChainAgent
from iris_langchain.callback import IrisCallbackHandler
from iris_langchain.tools import iris_tool_guard

__version__ = "0.1.0"

__all__ = [
    "IrisCallbackHandler",
    "IrisLangChainAgent",
    "iris_tool_guard",
    "IrisViolationError",
    "AgentPassport",
    "ComplianceTag",
    "DataClassification",
    "Environment",
    "ToolPermission",
    "PolicyResult",
    "Severity",
    "Violation",
]
