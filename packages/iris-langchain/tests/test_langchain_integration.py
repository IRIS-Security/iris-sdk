"""
Integration tests for iris-langchain callback, agent wrapper, and tool guard.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from iris import IrisViolationError
from iris_core.engine.cedar import CedarEngine
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import (
    AgentPassport,
    ComplianceTag,
    DataClassification,
    Environment,
    ToolPermission,
)
from iris_core.models.policy import Severity

from iris_langchain import IrisLangChainAgent, IrisCallbackHandler, iris_tool_guard


@pytest.fixture
def permitted_passport():
    return AgentPassport(
        name="support-agent",
        owner="team@company.com",
        data_classification=DataClassification.INTERNAL,
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
        environments=[Environment.DEV, Environment.PRODUCTION],
        is_high_risk_ai=True,
        evidence_vault_id="vault-abc",
        intent_ref="governance/agents/support-agent/policy-intent.md",
        tool_permissions=[
            ToolPermission(
                tool_id="lookup_account",
                description="Account lookup",
                allowed_actions=["call"],
            ),
        ],
    )


@pytest.fixture
def handler(permitted_passport):
    return IrisCallbackHandler(permitted_passport, Environment.DEV)


@pytest.fixture
def engine_with_policy(permitted_passport):
    engine = CedarEngine()
    engine.load_policy(permitted_passport.agent_id, "permit(principal, action, resource);")
    return engine


class TestIrisCallbackHandler:
    def test_callback_permits_allowed_tool(self, handler, permitted_passport, engine_with_policy):
        handler._engine = engine_with_policy
        handler.begin_run()
        handler.on_tool_start(
            {"name": "lookup_account", "description": "lookup"},
            '{"account_id": "1"}',
            run_id=uuid4(),
            inputs={"account_id": "1", "data_region": "us-east-1"},
        )

    def test_callback_blocks_denied_tool_in_production(
        self, handler, permitted_passport, engine_with_policy
    ):
        handler._engine = engine_with_policy
        handler.env = Environment.PRODUCTION
        with pytest.raises(IrisViolationError) as exc_info:
            handler.on_tool_start(
                {"name": "payments-api", "description": "payments"},
                "{}",
                run_id=uuid4(),
                inputs={},
            )
        assert exc_info.value.result.decision == "DENY"
        assert any(v.rule_id == "IRIS-TOOL-001" for v in exc_info.value.result.violations)

    def test_callback_warns_in_dev(self, handler, permitted_passport, engine_with_policy):
        handler._engine = engine_with_policy
        handler.env = Environment.DEV
        handler.on_tool_start(
            {"name": "unknown-tool", "description": "x"},
            "{}",
            run_id=uuid4(),
            inputs={},
        )

    def test_callback_blocks_cross_region_in_prod(self, handler, permitted_passport, engine_with_policy):
        handler._engine = engine_with_policy
        handler.env = Environment.PRODUCTION
        with pytest.raises(IrisViolationError):
            handler.on_tool_start(
                {"name": "lookup_account", "description": "lookup"},
                "{}",
                run_id=uuid4(),
                inputs={
                    "data_region": "cn-north-1",
                    "destination_region": "us-east-1",
                },
            )

    def test_no_policy_fail_open_in_dev(self, permitted_passport):
        h = IrisCallbackHandler(permitted_passport, Environment.DEV)
        h.on_tool_start(
            {"name": "any-tool", "description": ""},
            "{}",
            run_id=uuid4(),
            inputs={},
        )

    def test_no_policy_fail_closed_in_prod(self, permitted_passport):
        h = IrisCallbackHandler(permitted_passport, Environment.PRODUCTION)
        with pytest.raises(IrisViolationError) as exc_info:
            h.on_tool_start(
                {"name": "any-tool", "description": ""},
                "{}",
                run_id=uuid4(),
                inputs={},
            )
        assert exc_info.value.result.decision == "DENY"

    def test_pii_detection_in_tool_output(self, handler, permitted_passport, engine_with_policy):
        handler._engine = engine_with_policy
        handler.env = Environment.PRODUCTION
        handler.begin_run()
        run_id = uuid4()
        handler.on_tool_start(
            {"name": "lookup_account", "description": "lookup"},
            "{}",
            run_id=run_id,
            inputs={"data_region": "us-east-1"},
        )
        handler.on_tool_end(
            "Customer SSN is 123-45-6789",
            run_id=run_id,
        )
        events = handler._vault.get_events(limit=50)
        pii_events = [e for e in events if e.get("event_type") == "pii_output_guardrail"]
        assert len(pii_events) == 1
        assert pii_events[0]["decision"] == "VIOLATION"
        assert handler.current_run.pii_output_violations == 1

    def test_evidence_vault_records_per_run(self, handler, permitted_passport, engine_with_policy):
        handler._engine = engine_with_policy
        run_id = handler.begin_run()
        tool_run_id = uuid4()
        handler.on_tool_start(
            {"name": "lookup_account", "description": "lookup"},
            "{}",
            run_id=tool_run_id,
            inputs={"data_region": "us-east-1"},
        )
        handler.on_tool_end("Account active", run_id=tool_run_id)
        handler.finalize_run(output="done")

        events = handler._vault.get_events(limit=100)
        run_events = [e for e in events if e.get("run_id") == run_id]
        assert len(run_events) >= 3
        event_types = {e.get("event_type") for e in run_events}
        assert "run_start" in event_types
        assert "tool_end" in event_types
        assert "run_summary" in event_types

        summary_events = [e for e in run_events if e.get("event_type") == "run_summary"]
        summary = summary_events[0]["details"]["summary"]
        assert summary["run_id"] == run_id
        assert summary["total_tool_calls"] == 1
        assert "pass_rate" in summary


class TestIrisLangChainAgent:
    def test_agent_wraps_cleanly(self, permitted_passport):
        mock_agent = MagicMock()
        mock_agent.run.return_value = "ok"
        mock_agent.callbacks = []

        wrapped = IrisLangChainAgent.from_agent(mock_agent, permitted_passport)
        result = wrapped.run("hello")

        assert result == "ok"
        mock_agent.run.assert_called_once()
        assert wrapped._handler in mock_agent.callbacks
        assert wrapped._handler.current_run is not None
        assert wrapped._handler.current_run.finalized is True

    def test_compliance_check_on_agent(self, permitted_passport):
        incomplete = AgentPassport(
            name="loan-agent",
            owner="gmoney@gmail.com",
            compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
            is_high_risk_ai=True,
            evidence_vault_id=None,
            intent_ref=None,
        )
        mock_agent = MagicMock()
        mock_agent.callbacks = []
        wrapped = IrisLangChainAgent.from_agent(
            mock_agent,
            incomplete,
            compliance=["colorado-ai-act"],
        )
        violations = wrapped.compliance_check()
        rule_ids = {v.rule_id for v in violations}
        assert "CO-002" in rule_ids
        assert "CO-003" in rule_ids
        assert wrapped.is_ready_for_production is False

    def test_compliance_ready_when_complete(self, permitted_passport):
        mock_agent = MagicMock()
        mock_agent.callbacks = []
        wrapped = IrisLangChainAgent.from_agent(mock_agent, permitted_passport)
        assert wrapped.is_ready_for_production is True


class TestIrisToolGuard:
    def test_tool_guard_permits_declared_tool(self, permitted_passport, tmp_path):
        from langchain_core.tools import StructuredTool

        policy_file = tmp_path / "policy.cedar"
        policy_file.write_text("permit(principal, action, resource);")
        permitted_passport.policy_ref = str(policy_file)

        def lookup(account_id: str, data_region: str = "us-east-1") -> str:
            """Look up a customer account."""
            return account_id

        base = StructuredTool.from_function(lookup, name="lookup_account")
        guarded = iris_tool_guard(base, permitted_passport, environment="dev")
        result = guarded.invoke({"account_id": "42", "data_region": "us-east-1"})
        assert result == "42"

    def test_tool_guard_blocks_undeclared_in_prod(self, permitted_passport, tmp_path):
        from langchain_core.tools import StructuredTool

        policy_file = tmp_path / "policy.cedar"
        policy_file.write_text("permit(principal, action, resource);")
        permitted_passport.policy_ref = str(policy_file)

        def secret(action: str) -> str:
            """Perform a sensitive action."""
            return action

        base = StructuredTool.from_function(secret, name="secret-tool")
        guarded = iris_tool_guard(base, permitted_passport, environment="production")
        with pytest.raises(IrisViolationError):
            guarded.invoke({"action": "transfer"})
