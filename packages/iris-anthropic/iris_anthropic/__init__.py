"""
IRIS Anthropic integration — one-line drop-in for anthropic.Anthropic().

Quickstart:
    from iris_anthropic import IrisAnthropic
    from iris import AgentPassport, ComplianceTag

    passport = AgentPassport(
        name="support-agent",
        owner="team@company.com",
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    )
    client = IrisAnthropic(passport=passport)
    message = client.messages.create(model="claude-sonnet-4-6", ...)
"""

from __future__ import annotations

from iris import IrisViolationError
from iris_core.models.passport import (
    AgentPassport,
    ComplianceTag,
    DataClassification,
    Environment,
)
from iris_core.models.policy import Violation

from iris_anthropic.client import IrisAnthropic, IrisAnthropicAsync
from iris_anthropic.guardrails import check_prompt_for_violations

__version__ = "0.1.0"

__all__ = [
    "IrisAnthropic",
    "IrisAnthropicAsync",
    "IrisViolationError",
    "AgentPassport",
    "ComplianceTag",
    "DataClassification",
    "Environment",
    "Violation",
    "check_prompt_for_violations",
]
