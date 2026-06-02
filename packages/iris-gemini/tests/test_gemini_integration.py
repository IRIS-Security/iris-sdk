"""Integration tests for iris-gemini - mocked google-genai, no network calls."""

from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris import IrisViolationError
from iris_core.engine.cedar import CedarEngine
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, ComplianceTag, DataClassification, Environment
from iris_gemini import IrisGemini
from iris_gemini.guardrails import scan_gemini_content


@pytest.fixture
def compliant_passport():
    return AgentPassport(
        name="gemini-agent",
        owner="team@company.com",
        data_classification=DataClassification.INTERNAL,
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
        environments=[Environment.DEV, Environment.PRODUCTION],
        is_high_risk_ai=True,
        evidence_vault_id="vault-abc",
        intent_ref="governance/agents/gemini-agent/policy-intent.md",
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


def _mock_google_genai_module():
    genai_module = MagicMock()
    response = MagicMock()
    response.text = "Hello from Gemini"
    models = MagicMock()
    models.generate_content.return_value = response
    models.generate_content_stream.return_value = iter([response])
    models.generate_content_async = AsyncMock(return_value=response)
    models.generate_content_stream_async = AsyncMock(return_value=response)

    client = MagicMock()
    client.models = models
    client.api_key = "test-key"
    client.endpoint = "https://generativelanguage.googleapis.com"
    genai_module.Client.return_value = client

    google_module = types.ModuleType("google")
    google_module.genai = genai_module
    return google_module, genai_module, client


class Part:
    def __init__(self, text):
        self.text = text


class TestIrisGeminiClient:
    def test_client_permits_allowed_call(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        google_module, genai_module, mock_client = _mock_google_genai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"google": google_module, "google.genai": genai_module}):
            client = IrisGemini(passport=compliant_passport)
            client._engine = engine
            client._vault = vault
            result = client.models.generate_content(
                model="gemini-2.0-flash",
                contents="Help this customer.",
            )

        assert result.text == "Hello from Gemini"
        mock_client.models.generate_content.assert_called_once()
        events = vault.get_events()
        assert len(events) == 1
        assert events[0]["decision"] in ("PERMIT", "PERMIT_WITH_WARNINGS")
        assert events[0]["resource"] == "gemini-api/gemini-2.0-flash"

    def test_client_blocks_in_production(
        self, high_risk_incomplete_passport, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("IRIS_ENV", "production")
        google_module, genai_module, mock_client = _mock_google_genai_module()
        engine = CedarEngine()
        engine.load_policy(
            high_risk_incomplete_passport.agent_id,
            "permit(principal, action, resource);",
        )
        vault = EvidenceVault(
            agent_id=high_risk_incomplete_passport.agent_id,
            vault_dir=tmp_path,
        )

        with patch.dict("sys.modules", {"google": google_module, "google.genai": genai_module}):
            client = IrisGemini(passport=high_risk_incomplete_passport)
            client._engine = engine
            client._vault = vault
            with pytest.raises(IrisViolationError):
                client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents="Approve this loan application for decisioning.",
                )

        mock_client.models.generate_content.assert_not_called()

    def test_client_warns_in_dev(self, high_risk_incomplete_passport, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IRIS_ENV", "dev")
        google_module, genai_module, mock_client = _mock_google_genai_module()
        engine = CedarEngine()
        engine.load_policy(
            high_risk_incomplete_passport.agent_id,
            "permit(principal, action, resource);",
        )
        vault = EvidenceVault(
            agent_id=high_risk_incomplete_passport.agent_id,
            vault_dir=tmp_path,
        )

        with patch.dict("sys.modules", {"google": google_module, "google.genai": genai_module}):
            client = IrisGemini(passport=high_risk_incomplete_passport)
            client._engine = engine
            client._vault = vault
            client.models.generate_content(
                model="gemini-2.0-flash",
                contents="Approve this loan application for decisioning.",
            )

        mock_client.models.generate_content.assert_called_once()
        captured = capsys.readouterr()
        assert "[IRIS WARNING]" in captured.err

    def test_streaming_intercept(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        google_module, genai_module, mock_client = _mock_google_genai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"google": google_module, "google.genai": genai_module}):
            client = IrisGemini(passport=compliant_passport)
            client._engine = engine
            client._vault = vault
            stream = client.models.generate_content_stream(
                model="gemini-2.0-flash",
                contents="Stream a short response.",
            )
            list(stream)

        mock_client.models.generate_content_stream.assert_called_once()
        assert len(vault.get_events()) == 1

    def test_evidence_vault_records_call(self, compliant_passport, tmp_path, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        google_module, genai_module, _ = _mock_google_genai_module()
        engine = CedarEngine()
        engine.load_policy(compliant_passport.agent_id, "permit(principal, action, resource);")
        vault = EvidenceVault(agent_id=compliant_passport.agent_id, vault_dir=tmp_path)

        with patch.dict("sys.modules", {"google": google_module, "google.genai": genai_module}):
            client = IrisGemini(passport=compliant_passport)
            client._engine = engine
            client._vault = vault
            client.models.generate_content(model="gemini-2.0-flash", contents="First call")

        events = vault.get_events()
        assert len(events) == 1
        assert events[0]["action"] == "call"
        assert events[0]["resource"] == "gemini-api/gemini-2.0-flash"

    def test_drop_in_replacement_compatibility(self, compliant_passport, monkeypatch):
        monkeypatch.setenv("IRIS_ENV", "dev")
        google_module, genai_module, mock_client = _mock_google_genai_module()

        with patch.dict("sys.modules", {"google": google_module, "google.genai": genai_module}):
            client = IrisGemini(passport=compliant_passport, api_key="test-key")

        assert client.api_key == "test-key"
        assert client.endpoint == "https://generativelanguage.googleapis.com"
        genai_module.Client.assert_called_once_with(api_key="test-key")
        assert client.models is not None
        assert mock_client.models is not None


class TestGeminiGuardrails:
    def test_pii_detection_in_contents(self, compliant_passport):
        violations = scan_gemini_content(
            [Part("Customer SSN is 123-45-6789 for verification.")],
            compliant_passport,
        )
        assert any(v.rule_id == "IRIS-DATA-001" for v in violations)

    def test_cross_region_detection(self, compliant_passport):
        violations = scan_gemini_content(
            ["Send this data to beijing data center."],
            compliant_passport,
        )
        assert any(v.rule_id == "IRIS-XR-001" for v in violations)
