"""
Integration tests for iris-crewai agent wrapper, crew wrapper, and tool guard.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iris import IrisViolationError
from iris_core.engine.cedar import CedarEngine
from iris_core.models.passport import (
    AgentPassport,
    ComplianceTag,
    DataClassification,
    Environment,
    ToolPermission,
)

from iris_crewai import IrisCrew, IrisCrewAgent, iris_crew_tool


@pytest.fixture
def permitted_passport():
    return AgentPassport(
        name="researcher-agent",
        owner="team@company.com",
        data_classification=DataClassification.INTERNAL,
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
        environments=[Environment.DEV, Environment.PRODUCTION],
        is_high_risk_ai=True,
        evidence_vault_id="vault-abc",
        intent_ref="governance/agents/researcher-agent/policy-intent.md",
        tool_permissions=[
            ToolPermission(
                tool_id="web_search",
                description="Web search",
                allowed_actions=["call"],
            ),
        ],
    )


@pytest.fixture
def writer_passport():
    return AgentPassport(
        name="writer-agent",
        owner="team@company.com",
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
        tool_permissions=[
            ToolPermission(
                tool_id="write_summary",
                description="Write summary",
                allowed_actions=["call"],
            ),
        ],
    )


@pytest.fixture
def engine_with_policy(permitted_passport):
    engine = CedarEngine()
    engine.load_policy(permitted_passport.agent_id, "permit(principal, action, resource);")
    return engine


class TestIrisCrewAgent:
    def test_crew_agent_blocks_denied_tool(
        self, permitted_passport, engine_with_policy, tmp_path
    ):
        from crewai.tools import tool

        policy_file = tmp_path / "policy.cedar"
        policy_file.write_text("permit(principal, action, resource);")
        permitted_passport.policy_ref = str(policy_file)

        @tool
        def payments_api(action: str) -> str:
            """Execute a payment."""
            return action

        agent = IrisCrewAgent(
            permitted_passport,
            role="Researcher",
            goal="Research",
            backstory="Analyst",
            tools=[payments_api],
        )
        agent._iris_governor._engine = engine_with_policy
        agent._iris_governor.env = Environment.PRODUCTION
        governed_tool = agent.tools[0]

        with pytest.raises(IrisViolationError) as exc_info:
            governed_tool.run(action="transfer")

        assert exc_info.value.result.decision == "DENY"
        assert any(v.rule_id == "IRIS-TOOL-001" for v in exc_info.value.result.violations)

    def test_crew_agent_permits_allowed_tool(
        self, permitted_passport, engine_with_policy, tmp_path
    ):
        from crewai.tools import tool

        policy_file = tmp_path / "policy.cedar"
        policy_file.write_text("permit(principal, action, resource);")
        permitted_passport.policy_ref = str(policy_file)

        @tool
        def web_search(query: str, data_region: str = "us-east-1") -> str:
            """Search the web."""
            return query

        agent = IrisCrewAgent(
            permitted_passport,
            role="Researcher",
            goal="Research",
            backstory="Analyst",
            tools=[web_search],
        )
        agent._iris_governor._engine = engine_with_policy
        governed_tool = agent.tools[0]

        result = governed_tool.run(query="AI governance", data_region="us-east-1")
        assert result == "AI governance"


class TestIrisCrew:
    def test_crew_requires_all_passports(self, permitted_passport, writer_passport):
        from crewai import Crew

        researcher = IrisCrewAgent(
            permitted_passport,
            role="Researcher",
            goal="Research",
            backstory="Analyst",
        )
        writer = IrisCrewAgent(
            writer_passport,
            role="Writer",
            goal="Write",
            backstory="Writer",
        )
        base_crew = Crew(agents=[researcher, writer], tasks=[], verbose=False)

        with pytest.raises(ValueError, match="Missing passports"):
            IrisCrew.from_crew(base_crew, passports={"Researcher": permitted_passport})

    def test_crew_generates_compliance_report(self, permitted_passport, writer_passport):
        from iris_crewai._governance import EvaluationRecord

        researcher = IrisCrewAgent(
            permitted_passport,
            role="Researcher",
            goal="Research",
            backstory="Analyst",
        )
        writer = IrisCrewAgent(
            writer_passport,
            role="Writer",
            goal="Write",
            backstory="Writer",
        )

        researcher._iris_governor.records.append(
            EvaluationRecord(
                agent_name="researcher-agent",
                action="call",
                resource="web_search",
                decision="PERMIT",
            )
        )
        writer._iris_governor.records.append(
            EvaluationRecord(
                agent_name="writer-agent",
                action="call",
                resource="secret-tool",
                decision="DENY",
                violations=[
                    {"rule_id": "IRIS-TOOL-001", "severity": "critical", "message": "blocked"}
                ],
            )
        )

        base_crew = MagicMock()
        base_crew.agents = [researcher, writer]
        base_crew.kickoff.return_value = "done"

        crew = IrisCrew.from_crew(
            base_crew,
            passports={"Researcher": permitted_passport, "Writer": writer_passport},
        )
        crew.kickoff(inputs={"topic": "AI governance"})
        report = crew.compliance_report()

        assert report["total_evaluations"] == 2
        assert report["total_violations"] == 1
        assert report["violations_by_agent"]["writer-agent"] == 1
        assert report["violations_by_severity"]["critical"] == 1
        assert report["most_common_rule_violations"][0]["rule_id"] == "IRIS-TOOL-001"
        assert "Researcher" in report["agents"]
        assert "Writer" in report["agents"]


class TestIrisCrewTool:
    def test_iris_crew_tool_decorator(self, permitted_passport, engine_with_policy, tmp_path):
        from crewai.tools import tool

        policy_file = tmp_path / "policy.cedar"
        policy_file.write_text("permit(principal, action, resource);")
        permitted_passport.policy_ref = str(policy_file)

        @tool
        def web_search(query: str, data_region: str = "us-east-1") -> str:
            """Search the web."""
            return query

        guarded = iris_crew_tool(web_search, permitted_passport, environment="dev")
        assert guarded.name == "web_search"
        assert "Search the web" in guarded.description
        assert guarded.args_schema is not None

        result = guarded.run(query="AI governance", data_region="us-east-1")
        assert result == "AI governance"

    def test_iris_crew_tool_blocks_undeclared_in_prod(
        self, permitted_passport, engine_with_policy, tmp_path
    ):
        from crewai.tools import tool

        policy_file = tmp_path / "policy.cedar"
        policy_file.write_text("permit(principal, action, resource);")
        permitted_passport.policy_ref = str(policy_file)

        @tool
        def secret_tool(action: str) -> str:
            """Perform a sensitive action."""
            return action

        guarded = iris_crew_tool(secret_tool, permitted_passport, environment="production")
        with pytest.raises(IrisViolationError):
            guarded.run(action="transfer")
