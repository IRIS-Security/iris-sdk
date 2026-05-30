"""
IRIS CrewAI integration — governance in two lines per agent.

Quickstart:
    from iris_crewai import IrisCrewAgent, IrisCrew
    from iris import AgentPassport, ComplianceTag

    passport = AgentPassport(
        name="researcher-agent",
        owner="team@company.com",
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    )
    agent = IrisCrewAgent(passport, role="Researcher", goal="...", backstory="...")
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

from iris_crewai.agent import IrisCrewAgent
from iris_crewai.crew import IrisCrew
from iris_crewai.tools import iris_crew_tool

__version__ = "0.1.0"

__all__ = [
    "IrisCrewAgent",
    "IrisCrew",
    "iris_crew_tool",
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
