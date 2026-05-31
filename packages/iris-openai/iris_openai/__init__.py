"""
IRIS OpenAI integration — one-line drop-in for openai.OpenAI().

Quickstart:
    from iris_openai import IrisOpenAI
    from iris import AgentPassport, ComplianceTag

    passport = AgentPassport(
        name="analysis-agent",
        owner="team@company.com",
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    )
    client = IrisOpenAI(passport=passport)
    response = client.chat.completions.create(model="gpt-4o", messages=[...])
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
from iris_core.models.policy import Violation

from iris_openai.client import IrisAzureOpenAI, IrisOpenAI, IrisOpenAIAsync
from iris_openai.tool_guard import guard_openai_tools

__version__ = "0.1.0"

__all__ = [
    "IrisOpenAI",
    "IrisOpenAIAsync",
    "IrisAzureOpenAI",
    "IrisViolationError",
    "AgentPassport",
    "ComplianceTag",
    "DataClassification",
    "Environment",
    "ToolPermission",
    "Violation",
    "guard_openai_tools",
]
