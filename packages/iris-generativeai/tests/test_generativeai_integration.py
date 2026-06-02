"""Integration tests for iris-generativeai with mocked google-generativeai."""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from iris import IrisViolationError
from iris_core.engine.cedar import CedarEngine
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, ComplianceTag, DataClassification, Environment
from iris_generativeai import IrisGenerativeAI


@pytest.fixture
def compliant_passport():
    return AgentPassport(
        name="legacy-gemini-agent",
        owner="team@company.com",
        data_classification=DataClassification.INTERNAL,
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
        environments=[Environment.DEV, Environment.PRODUCTION],
        is_high_risk_ai=True,
        evidence_vault_id="vault-abc",
        intent_ref="governance/agents/legacy-gemini-agent/policy-intent.md",
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


def _mock_google_generativeai_module():
    genai_module = types.ModuleType("google.generativeai")

    response = MagicMock()
    response.text = "Hello from legacy Gemini"

    chat_session = MagicMock()
    chat_session.send_message.return_value = response

    model = MagicMock()
    model.generate_content.return_value = response
    model.generate_content_async = MagicMock(return_value=response)
    model.start_chat.return_value = chat_session
    model.count_tokens.return_value = {"total_tokens": 12}

    configure_mock = MagicMock()
    generative_model_ctor = MagicMock(return_value=model)

    genai_module.configure = configure_mock
    genai_module.GenerativeModel = generative_model_ctor

    google_module = types.ModuleType("google")
    google_module.generativeai = genai_module
    return google_module, genai_module, configure_mock, generative_model_ctor, model, chat_session


class TestIrisGenerativeAI:
    def test_model_permits_allowed_call(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        (
            google_module,
            genai_module,
            configure_mock,
            generative_model_ctor,
            model_mock,
            _,
        ) = _mock_google_generativeai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict(
            "sys.modules", {"google": google_module, "google.generativeai": genai_module}
        ):
            client = IrisGenerativeAI(passport=compliant_passport)
            client._engine = engine
            client._vault = vault
            governed_model = client.GenerativeModel("gemini-1.5-pro")
            result = governed_model.generate_content("Help this customer.")

        assert result.text == "Hello from legacy Gemini"
        configure_mock.assert_called_once_with(api_key="test-key")
        generative_model_ctor.assert_called_once_with("gemini-1.5-pro")
        model_mock.generate_content.assert_called_once()
        events = vault.get_events()
        assert len(events) == 1
        assert events[0]["decision"] in ("PERMIT", "PERMIT_WITH_WARNINGS")
        assert events[0]["resource"] == "gemini-api/gemini-1.5-pro"

    def test_model_blocks_in_production(
        self, high_risk_incomplete_passport, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("IRIS_ENV", "production")
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        (
            google_module,
            genai_module,
            _,
            _,
            model_mock,
            _,
        ) = _mock_google_generativeai_module()
        engine = CedarEngine()
        engine.load_policy(
            high_risk_incomplete_passport.agent_id,
            "permit(principal, action, resource);",
        )
        vault = EvidenceVault(agent_id=high_risk_incomplete_passport.agent_id, vault_dir=tmp_path)

        with patch.dict(
            "sys.modules", {"google": google_module, "google.generativeai": genai_module}
        ):
            client = IrisGenerativeAI(passport=high_risk_incomplete_passport)
            client._engine = engine
            client._vault = vault
            governed_model = client.GenerativeModel("gemini-1.5-pro")
            with pytest.raises(IrisViolationError):
                governed_model.generate_content("Approve this loan application.")

        model_mock.generate_content.assert_not_called()

    def test_chat_session_intercept(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        (
            google_module,
            genai_module,
            _,
            _,
            _,
            chat_session_mock,
        ) = _mock_google_generativeai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict(
            "sys.modules", {"google": google_module, "google.generativeai": genai_module}
        ):
            client = IrisGenerativeAI(passport=compliant_passport)
            client._engine = engine
            client._vault = vault
            chat = client.GenerativeModel("gemini-1.5-pro").start_chat(history=[])
            chat.send_message("Help this customer over chat.")

        chat_session_mock.send_message.assert_called_once()
        assert len(vault.get_events()) == 1

    def test_evidence_vault_records_call(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        (
            google_module,
            genai_module,
            _,
            _,
            _,
            _,
        ) = _mock_google_generativeai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict(
            "sys.modules", {"google": google_module, "google.generativeai": genai_module}
        ):
            client = IrisGenerativeAI(passport=compliant_passport)
            client._engine = engine
            client._vault = vault
            model = client.GenerativeModel("gemini-1.5-pro")
            model.generate_content("First call")

        events = vault.get_events()
        assert len(events) == 1
        assert events[0]["action"] == "call"
        assert events[0]["resource"] == "gemini-api/gemini-1.5-pro"
