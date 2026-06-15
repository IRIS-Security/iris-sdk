"""Integration tests for model governance in iris-anthropic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iris_core.engine.cedar import CedarEngine
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment
from iris_anthropic import IrisAnthropic


REGISTRY_YAML = """
apiVersion: iris.io/v1alpha1
kind: ModelRegistry
spec:
  models:
    claude-sonnet-4-6:
      provider: anthropic
      tier: standard
    claude-fable-5:
      provider: anthropic
      tier: frontier-restricted
      fallback_model: claude-sonnet-4-6
"""

DIRECTIVES_YAML = """
apiVersion: iris.io/v1alpha1
kind: DirectiveRegistry
spec:
  directives:
    - directive_id: test-suspend
      model_id: claude-fable-5
      status: suspended
      fallback_model: claude-sonnet-4-6
"""


@pytest.fixture
def governance_root(tmp_path: Path) -> Path:
    (tmp_path / "models").mkdir()
    (tmp_path / "directives").mkdir()
    (tmp_path / "models" / "registry.yaml").write_text(REGISTRY_YAML)
    (tmp_path / "directives" / "active.yaml").write_text(DIRECTIVES_YAML)
    return tmp_path


@pytest.fixture
def passport() -> AgentPassport:
    return AgentPassport(
        name="security-agent",
        owner="sec@company.com",
        environments=[Environment.DEV, Environment.PRODUCTION],
    )


def _mock_anthropic():
    mock_module = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_module.Anthropic.return_value = mock_client
    return mock_module, mock_client


def test_auto_fallback_on_suspended_model(
    passport: AgentPassport, governance_root: Path, monkeypatch, capsys
):
    monkeypatch.setenv("IRIS_ENV", "dev")
    mock_module, mock_client = _mock_anthropic()
    engine = CedarEngine(governance_root=governance_root)
    engine.load_policy(passport.agent_id, "permit(principal, action, resource);")
    vault = EvidenceVault(agent_id=passport.agent_id)

    with patch.dict("sys.modules", {"anthropic": mock_module}):
        client = IrisAnthropic(passport=passport, auto_fallback=True)
        client._engine = engine
        client._vault = vault
        client.messages.create(
            model="claude-fable-5",
            max_tokens=100,
            messages=[{"role": "user", "content": "audit this repo"}],
        )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-6"
    assert "auto-fallback" in capsys.readouterr().err
