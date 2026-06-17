"""Tests for the IRIS MCP server package."""

from __future__ import annotations

from pathlib import Path

import pytest

from iris_core.entitlements import Entitlements, Feature
from iris_mcp.server import collect_tools
from iris_mcp.tools import compliance, cost, discovery, hitl


@pytest.fixture(autouse=True)
def clear_license(monkeypatch, tmp_path):
    monkeypatch.delenv("IRIS_LICENSE_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    license_file = tmp_path / ".iris" / "license.key"
    if license_file.exists():
        license_file.unlink()
    yield


def test_server_starts_and_lists_tools():
    tools = collect_tools(include_pro=True)
    names = {tool.name for tool in tools}
    assert "iris_scan_discover" in names
    assert "iris_compliance_check" in names
    assert "iris_hitl_list" in names
    assert len(tools) >= 20


def test_free_tools_available_without_license():
    tools = collect_tools(include_pro=False)
    names = {tool.name for tool in tools}
    assert "iris_scan_discover" in names
    assert "iris_framework_suggest" in names
    assert "iris_hitl_list" not in names
    assert "iris_cost_report" not in names


def test_pro_tools_require_license():
    free_tools = collect_tools(include_pro=False)
    pro_tools = collect_tools(include_pro=True)
    assert len(pro_tools) > len(free_tools)
    assert not Entitlements().has(Feature.BUNDLE_HIPAA)


@pytest.mark.asyncio
async def test_scan_discover_tool_returns_findings(tmp_path):
    sample = tmp_path / "bot.py"
    sample.write_text("from openai import OpenAI\nclient = OpenAI()\n")
    result = await discovery.scan_discover({"directory": str(tmp_path)})
    text = result[0].text
    assert "Discovery Scan" in text
    assert "bot.py" in text or "Ungoverned" in text or "No ungoverned" in text


@pytest.mark.asyncio
async def test_compliance_check_tool_returns_results(tmp_path, monkeypatch):
    gov = tmp_path / "governance" / "agents" / "demo-agent"
    gov.mkdir(parents=True)
    (gov / "passport.yaml").write_text(
        """apiVersion: iris.ai/v1
kind: AgentPassport
metadata:
  name: demo-agent
spec:
  name: demo-agent
  owner: test@example.com
  team: test
  compliance_tags:
    - colorado-ai-act
  is_high_risk_ai: true
"""
    )
    monkeypatch.chdir(tmp_path)
    result = await compliance.check({"framework": "colorado-ai-act", "agent_name": "demo-agent"})
    text = result[0].text
    assert "demo-agent" in text
    assert "CO-" in text or "PASS" in text or "FAIL" in text


@pytest.mark.asyncio
async def test_framework_suggest_returns_recommendations():
    result = await compliance.framework_suggest(
        {
            "domain": "loan processing for Colorado consumers",
            "data_types": "financial account data",
            "user_locations": "Colorado",
        }
    )
    text = result[0].text
    assert "colorado-ai-act" in text.lower()
    assert "Framework" in text


@pytest.mark.asyncio
async def test_hitl_list_requires_pro():
    result = await hitl.list_reviews({})
    assert "IRIS Pro" in result[0].text


@pytest.mark.asyncio
async def test_cost_report_requires_pro():
    result = await cost.report({})
    assert "IRIS Pro" in result[0].text


@pytest.mark.asyncio
async def test_upgrade_message_is_helpful():
    result = await compliance.assess({"agent_name": "demo"})
    text = result[0].text
    assert "iris license activate" in text
    assert "impact assessment" in text.lower()
