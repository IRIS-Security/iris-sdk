"""Integration tests for iris-vertexai with mocked Vertex AI SDK."""

from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iris import IrisViolationError
from iris_core.engine.cedar import CedarEngine
from iris_core.models.passport import AgentPassport, ComplianceTag, DataClassification, Environment
from iris_vertexai import IrisVertexAI
from iris_vertexai.fedramp import check_fedramp_location, check_fedramp_model


def _mock_vertex_modules():
    vertexai_module = types.ModuleType("vertexai")
    vertexai_module.init = MagicMock()

    gm_module = types.ModuleType("vertexai.generative_models")
    response = MagicMock()
    response.text = "Vertex response"
    chat_response = MagicMock()
    chat_response.text = "chat response"
    chat_session = MagicMock()
    chat_session.send_message.return_value = chat_response

    model_instance = MagicMock()
    model_instance.generate_content.return_value = response
    model_instance.generate_content_stream.return_value = iter([response])
    model_instance.start_chat.return_value = chat_session

    gm_module.GenerativeModel = MagicMock(return_value=model_instance)
    return vertexai_module, gm_module, model_instance, chat_session


class _FedrampTag:
    value = "fedramp"


@pytest.fixture
def passport():
    return AgentPassport(
        name="vertex-agent",
        owner="team@gov-agency.gov",
        data_classification=DataClassification.INTERNAL,
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
        environments=[Environment.DEV, Environment.PRODUCTION],
        allowed_regions=["us-central1", "us-east1"],
    )


def _permit_engine(passport: AgentPassport) -> CedarEngine:
    engine = CedarEngine()
    engine.load_policy(passport.agent_id, "permit(principal, action, resource);")
    return engine


def test_authorized_location_permitted(passport, tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_ENV", "dev")
    vertexai_module, gm_module, model_instance, _ = _mock_vertex_modules()

    with patch.dict(
        "sys.modules",
        {"vertexai": vertexai_module, "vertexai.generative_models": gm_module},
    ):
        client = IrisVertexAI(
            passport=passport,
            project="proj-1",
            location="us-central1",
            evidence_vault_dir=tmp_path,
        )
        client._engine = _permit_engine(passport)
        model = client.get_model("gemini-1.5-pro")
        result = model.generate_content("hello")

    assert result.text == "Vertex response"
    model_instance.generate_content.assert_called_once()


def test_unauthorized_location_blocked(passport, tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_ENV", "production")
    vertexai_module, gm_module, model_instance, _ = _mock_vertex_modules()

    with patch.dict(
        "sys.modules",
        {"vertexai": vertexai_module, "vertexai.generative_models": gm_module},
    ):
        client = IrisVertexAI(
            passport=passport,
            project="proj-1",
            location="europe-west1",
            evidence_vault_dir=tmp_path,
        )
        client._engine = _permit_engine(passport)
        model = client.get_model("gemini-1.5-pro")
        with pytest.raises(IrisViolationError):
            model.generate_content("hello")

    model_instance.generate_content.assert_not_called()


def test_fedramp_location_check():
    assert check_fedramp_location("us-central1") is None
    violation = check_fedramp_location("europe-west1")
    assert violation is not None
    assert violation.rule_id == "FEDRAMP-001"


def test_fedramp_model_check():
    assert check_fedramp_model("gemini-1.5-pro") is None
    violation = check_fedramp_model("gemini-2.0-flash")
    assert violation is not None
    assert violation.rule_id == "FEDRAMP-002"


def test_chat_session_intercept(passport, tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_ENV", "dev")
    vertexai_module, gm_module, _, chat_session = _mock_vertex_modules()

    with patch.dict(
        "sys.modules",
        {"vertexai": vertexai_module, "vertexai.generative_models": gm_module},
    ):
        client = IrisVertexAI(
            passport=passport,
            project="proj-1",
            location="us-central1",
            evidence_vault_dir=tmp_path,
        )
        client._engine = _permit_engine(passport)
        model = client.get_model("gemini-1.5-pro")
        chat = model.start_chat()
        chat.send_message("hello")

    chat_session.send_message.assert_called_once()


def test_evidence_vault_includes_gcp_metadata(passport, tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_ENV", "dev")
    vertexai_module, gm_module, _, _ = _mock_vertex_modules()
    passport.compliance_tags = [ComplianceTag.COLORADO_AI_ACT, _FedrampTag()]

    with patch.dict(
        "sys.modules",
        {"vertexai": vertexai_module, "vertexai.generative_models": gm_module},
    ):
        client = IrisVertexAI(
            passport=passport,
            project="proj-1",
            location="us-central1",
            evidence_vault_dir=tmp_path,
        )
        client._engine = _permit_engine(passport)
        model = client.get_model("gemini-1.5-pro")
        model.generate_content("hello")

    events_file = Path(tmp_path) / passport.agent_id / "events.jsonl"
    lines = events_file.read_text().strip().splitlines()
    event = json.loads(lines[-1])
    assert event["gcp_project"] == "proj-1"
    assert event["gcp_location"] == "us-central1"
    assert event["additional"]["gcp_project"] == "proj-1"
    assert event["additional"]["gcp_location"] == "us-central1"
