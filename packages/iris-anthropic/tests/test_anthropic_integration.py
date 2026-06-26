"""
Integration tests for iris-anthropic — mocked Anthropic API, no network calls.
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
)
from iris_anthropic import IrisAnthropic, check_prompt_for_violations
from iris_anthropic.guardrails import prompt_suggests_pii


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


def _mock_anthropic_module():
    mock_module = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hello from Claude")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.messages.stream.return_value = iter([mock_response])
    mock_module.Anthropic.return_value = mock_client
    return mock_module, mock_client


def _call_events(vault: EvidenceVault) -> list[dict]:
    return [event for event in vault.get_events() if "decision" in event]


class TestIrisAnthropicClient:
    def test_client_permits_allowed_call(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, mock_client = _mock_anthropic_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            client = IrisAnthropic(passport=compliant_passport)
            client._engine = engine
            client._vault = vault

            result = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": "Help this customer."}],
            )

        assert result.content[0].text == "Hello from Claude"
        mock_client.messages.create.assert_called_once()
        events = _call_events(vault)
        assert len(events) == 1
        assert events[0]["decision"] in ("PERMIT", "PERMIT_WITH_WARNINGS")

    def test_client_blocks_denied_call_in_production(
        self, high_risk_incomplete_passport, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("IRIS_ENV", "production")
        mock_module, _ = _mock_anthropic_module()
        engine = CedarEngine()
        engine.load_policy(
            high_risk_incomplete_passport.agent_id,
            "permit(principal, action, resource);",
        )
        vault = EvidenceVault(
            agent_id=high_risk_incomplete_passport.agent_id, vault_dir=tmp_path
        )

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            client = IrisAnthropic(passport=high_risk_incomplete_passport)
            client._engine = engine
            client._vault = vault

            with pytest.raises(IrisViolationError) as exc_info:
                client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    messages=[{"role": "user", "content": "Help this customer."}],
                )

        assert exc_info.value.result.decision == "DENY"
        assert exc_info.value.result.violations
        assert any(
            v.rule_id.startswith("CO-") for v in exc_info.value.result.violations
        )
        mock_module.Anthropic.return_value.messages.create.assert_not_called()

    def test_client_warns_in_dev_environment(
        self, high_risk_incomplete_passport, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, mock_client = _mock_anthropic_module()
        engine = CedarEngine()
        engine.load_policy(
            high_risk_incomplete_passport.agent_id,
            "permit(principal, action, resource);",
        )
        vault = EvidenceVault(
            agent_id=high_risk_incomplete_passport.agent_id, vault_dir=tmp_path
        )

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            client = IrisAnthropic(passport=high_risk_incomplete_passport)
            client._engine = engine
            client._vault = vault

            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": "Help this customer."}],
            )

        mock_client.messages.create.assert_called_once()
        captured = capsys.readouterr()
        assert "[IRIS WARNING]" in captured.err
        events = _call_events(vault)
        assert events
        assert events[0]["decision"] in ("DENY", "PERMIT_WITH_WARNINGS")

    def test_streaming_intercept(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, mock_client = _mock_anthropic_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            client = IrisAnthropic(passport=compliant_passport)
            client._engine = engine
            client._vault = vault

            stream = client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=256,
                messages=[{"role": "user", "content": "Stream a short reply."}],
            )
            list(stream)

        mock_client.messages.stream.assert_called_once()
        assert len(_call_events(vault)) == 1

    def test_evidence_vault_records_every_call(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, _ = _mock_anthropic_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            client = IrisAnthropic(passport=compliant_passport)
            client._engine = engine
            client._vault = vault

            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "First call"}],
            )
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "Second call"}],
            )

        events = _call_events(vault)
        assert len(events) == 2
        assert all(e["action"] == "call" for e in events)
        assert all(e["resource"] == "anthropic-api" for e in events)

    def test_drop_in_replacement_api_compatibility(self, compliant_passport, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        mock_module, mock_client = _mock_anthropic_module()
        mock_client.api_key = "sk-test-key"
        mock_client.base_url = "https://api.anthropic.com"

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            client = IrisAnthropic(passport=compliant_passport, api_key="sk-test-key")

        assert client.api_key == "sk-test-key"
        assert client.base_url == "https://api.anthropic.com"
        mock_module.Anthropic.assert_called_once_with(api_key="sk-test-key")


class TestPromptGuardrails:
    def test_pii_pattern_detection_in_prompt(self, compliant_passport):
        violations = check_prompt_for_violations(
            "Customer SSN is 123-45-6789 for verification.",
            compliant_passport,
        )
        assert any(v.rule_id == "IRIS-DATA-001" for v in violations)
        assert prompt_suggests_pii("123-45-6789")

    def test_cross_region_pattern_in_prompt(self, compliant_passport):
        violations = check_prompt_for_violations(
            "Deploy model to cn-north-1 region.",
            compliant_passport,
        )
        assert any(v.rule_id == "IRIS-XR-001" for v in violations)

    def test_high_risk_domain_keyword(self, compliant_passport):
        violations = check_prompt_for_violations(
            "Review this loan application for approval.",
            compliant_passport,
        )
        assert any(v.rule_id == "CO-004" for v in violations)

    def test_production_blocks_cross_region_prompt(
        self, compliant_passport, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("IRIS_ENV", "production")
        mock_module, mock_client = _mock_anthropic_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            client = IrisAnthropic(passport=compliant_passport)
            client._engine = engine
            client._vault = vault

            with pytest.raises(IrisViolationError) as exc_info:
                client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=100,
                    messages=[
                        {
                            "role": "user",
                            "content": "Send data to beijing data center.",
                        }
                    ],
                )

        assert any(v.rule_id == "IRIS-XR-001" for v in exc_info.value.result.violations)
        mock_client.messages.create.assert_not_called()
