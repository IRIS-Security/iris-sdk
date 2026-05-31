"""
Integration tests for iris-openai — mocked OpenAI API, no network calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
from iris_openai import IrisAzureOpenAI, IrisOpenAI, guard_openai_tools
from iris_openai._governance import parse_azure_endpoint_region


@pytest.fixture
def compliant_passport():
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
            ToolPermission(tool_id="search", description="Search", allowed_actions=["call"]),
        ],
    )


@pytest.fixture
def high_risk_incomplete_passport():
    return AgentPassport(
        name="loan-agent",
        owner="gmoney@gmail.com",
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
        environments=[Environment.DEV, Environment.PRODUCTION],
        is_high_risk_ai=True,
        evidence_vault_id=None,
        intent_ref=None,
    )


def _mock_openai_module():
    mock_module = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Hello from GPT"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    mock_client.chat.completions.stream.return_value = iter([mock_response])
    mock_client.embeddings.create.return_value = MagicMock(data=[])
    mock_module.OpenAI.return_value = mock_client
    mock_module.AzureOpenAI.return_value = mock_client
    return mock_module, mock_client


def _search_tool():
    return {
        "type": "function",
        "function": {"name": "search", "description": "search", "parameters": {}},
    }


def _payments_tool():
    return {
        "type": "function",
        "function": {"name": "payments", "description": "pay", "parameters": {}},
    }


class TestIrisOpenAIClient:
    def test_client_permits_allowed_call(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, mock_client = _mock_openai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"openai": mock_module}):
            client = IrisOpenAI(passport=compliant_passport)
            client._engine = engine
            client._vault = vault

            result = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Help this customer."}],
            )

        assert result.choices[0].message.content == "Hello from GPT"
        mock_client.chat.completions.create.assert_called_once()
        events = vault.get_events()
        assert len(events) == 1
        assert events[0]["decision"] in ("PERMIT", "PERMIT_WITH_WARNINGS")
        assert events[0]["resource"] == "openai-api"

    def test_client_blocks_in_production(
        self, high_risk_incomplete_passport, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("IRIS_ENV", "production")
        mock_module, _ = _mock_openai_module()
        engine = CedarEngine()
        engine.load_policy(
            high_risk_incomplete_passport.agent_id,
            "permit(principal, action, resource);",
        )
        vault = EvidenceVault(
            agent_id=high_risk_incomplete_passport.agent_id, vault_dir=tmp_path
        )

        with patch.dict("sys.modules", {"openai": mock_module}):
            client = IrisOpenAI(passport=high_risk_incomplete_passport)
            client._engine = engine
            client._vault = vault

            with pytest.raises(IrisViolationError) as exc_info:
                client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": "Help this customer."}],
                )

        assert exc_info.value.result.decision == "DENY"
        assert any(v.rule_id == "CO-001" for v in exc_info.value.result.violations)
        mock_module.OpenAI.return_value.chat.completions.create.assert_not_called()

    def test_client_warns_in_dev(
        self, high_risk_incomplete_passport, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, mock_client = _mock_openai_module()
        engine = CedarEngine()
        engine.load_policy(
            high_risk_incomplete_passport.agent_id,
            "permit(principal, action, resource);",
        )
        vault = EvidenceVault(
            agent_id=high_risk_incomplete_passport.agent_id, vault_dir=tmp_path
        )

        with patch.dict("sys.modules", {"openai": mock_module}):
            client = IrisOpenAI(passport=high_risk_incomplete_passport)
            client._engine = engine
            client._vault = vault

            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Help this customer."}],
            )

        mock_client.chat.completions.create.assert_called_once()
        captured = capsys.readouterr()
        assert "[IRIS WARNING]" in captured.err
        events = vault.get_events()
        assert events[0]["decision"] == "DENY"

    def test_tool_filtering_removes_unpermitted_tools(
        self, compliant_passport, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, mock_client = _mock_openai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"openai": mock_module}):
            client = IrisOpenAI(passport=compliant_passport)
            client._engine = engine
            client._vault = vault

            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Run tools"}],
                tools=[_search_tool(), _payments_tool()],
            )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        tool_names = [t["function"]["name"] for t in call_kwargs["tools"]]
        assert tool_names == ["search"]
        assert "payments" not in tool_names
        captured = capsys.readouterr()
        assert "IRIS TOOL FILTER" in captured.err
        assert "payments" in captured.err

    def test_azure_openai_cross_region_detection(
        self, compliant_passport, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("IRIS_ENV", "production")
        eu_passport = AgentPassport(
            name=compliant_passport.name,
            owner=compliant_passport.owner,
            agent_id=compliant_passport.agent_id,
            data_classification=DataClassification.PII,
            allowed_regions=["eu-west-1"],
            environments=[Environment.PRODUCTION],
            compliance_tags=[ComplianceTag.GDPR],
        )
        mock_module, mock_client = _mock_openai_module()
        engine = CedarEngine()
        engine.load_policy(eu_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=eu_passport.agent_id, vault_dir=tmp_path)

        endpoint = "https://my-resource-eastus.cognitiveservices.azure.com/openai"
        assert parse_azure_endpoint_region(endpoint) == "us-east-1"

        with patch.dict("sys.modules", {"openai": mock_module}):
            client = IrisAzureOpenAI(
                passport=eu_passport,
                azure_endpoint=endpoint,
                api_key="test",
            )
            client._engine = engine
            client._vault = vault

            with pytest.raises(IrisViolationError) as exc_info:
                client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": "Process EU data."}],
                )

        assert any(v.rule_id == "IRIS-XR-001" for v in exc_info.value.result.violations)
        mock_client.chat.completions.create.assert_not_called()

    def test_embeddings_intercept(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, mock_client = _mock_openai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"openai": mock_module}):
            client = IrisOpenAI(passport=compliant_passport)
            client._engine = engine
            client._vault = vault

            client.embeddings.create(model="text-embedding-3-small", input="hello")

        mock_client.embeddings.create.assert_called_once()
        events = vault.get_events()
        assert len(events) == 1
        assert events[0]["resource"] == "openai-api"

    def test_streaming_intercept(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, mock_client = _mock_openai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"openai": mock_module}):
            client = IrisOpenAI(passport=compliant_passport)
            client._engine = engine
            client._vault = vault

            stream = client.chat.completions.stream(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Stream a reply."}],
            )
            list(stream)

        mock_client.chat.completions.stream.assert_called_once()
        assert len(vault.get_events()) == 1

    def test_evidence_vault_records_call(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, _ = _mock_openai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"openai": mock_module}):
            client = IrisOpenAI(passport=compliant_passport)
            client._engine = engine
            client._vault = vault

            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "First"}],
            )
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Second"}],
            )

        events = vault.get_events()
        assert len(events) == 2
        assert all(e["action"] == "call" for e in events)
        assert all(e["resource"] == "openai-api" for e in events)


class TestGuardOpenAITools:
    def test_production_blocks_all_tools_without_permissions(self, monkeypatch, capsys):
        monkeypatch.setenv("IRIS_ENV", "production")
        passport = AgentPassport(
            name="no-tools",
            owner="team@company.com",
            environments=[Environment.PRODUCTION],
        )
        filtered = guard_openai_tools([_search_tool(), _payments_tool()], passport)
        assert filtered == []
        assert "IRIS TOOL FILTER" in capsys.readouterr().err

    def test_guard_returns_only_permitted(self, compliant_passport, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "production")
        filtered = guard_openai_tools(
            [_search_tool(), _payments_tool()],
            compliant_passport,
            Environment.PRODUCTION,
        )
        assert len(filtered) == 1
        assert filtered[0]["function"]["name"] == "search"
