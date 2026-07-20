"""Tests for iris-agt profile mapping."""

from __future__ import annotations

import json

import pytest

from iris_agt._profile import build_profile_from_agt_entries
from iris_agt.reader import (
    _FORBIDDEN_CONTENT_FIELDS,
    _normalize_entry,
    parse_agt_audit_trail,
    profile_from_agt,
    verify_chain_continuity,
)

FIXTURE_ENTRIES = [
    {
        "entry_id": "e1",
        "event_type": "tool_invocation",
        "agent_did": "did:web:sales-assistant.example.com",
        "action": "allow",
        "resource": "/crm/contacts",
        "data": {"tool": "crm_lookup", "query": "acme corp"},
        "outcome": "success",
        "policy_decision": "allowed",
        "previous_hash": "genesis",
        "entry_hash": "hash1",
    },
    {
        "entry_id": "e2",
        "event_type": "tool_invocation",
        "agent_did": "did:web:sales-assistant.example.com",
        "action": "allow",
        "resource": "/support/public-customer-portal",
        "data": {"tool": "ticket_lookup"},
        "outcome": "success",
        "policy_decision": "allowed",
        "matched_rule": "phi patient_id lookup rule",
        "previous_hash": "hash1",
        "entry_hash": "hash2",
    },
    {
        "entry_id": "e3",
        "event_type": "policy_violation",
        "agent_did": "did:web:sales-assistant.example.com",
        "action": "deny",
        "resource": "/finance/ledger",
        "data": {"tool": "ledger_export"},
        "outcome": "denied",
        "previous_hash": "hash2",
        "entry_hash": "hash3",
    },
]


def test_profile_mapping_from_fixture_entries():
    profile = build_profile_from_agt_entries(FIXTURE_ENTRIES)
    assert profile["source"] == "sdk_scan"
    assert profile["models"] == []
    assert profile["providers"] == []
    assert profile["frameworks"] == []
    assert "phi" in profile["data_categories"]
    assert profile["agent_count"] == 1
    assert profile["autonomy_level"] == "supervised"
    assert profile["customer_facing"] is True
    assert set(profile.keys()) == {
        "source",
        "models",
        "providers",
        "frameworks",
        "data_categories",
        "deployment_regions",
        "agent_count",
        "autonomy_level",
        "customer_facing",
    }


def test_autonomy_thresholds():
    assistive = build_profile_from_agt_entries(
        [{"agent_did": "a1", "event_type": "policy_evaluation", "action": "allow"}]
    )
    assert assistive["autonomy_level"] == "assistive"

    supervised = build_profile_from_agt_entries(
        [{"agent_did": "a1", "event_type": "tool_invocation", "action": "allow"}]
    )
    assert supervised["autonomy_level"] == "supervised"

    autonomous_by_count = build_profile_from_agt_entries(
        [{"agent_did": "a1", "event_type": "tool_invocation", "action": "allow"}] * 10
    )
    assert autonomous_by_count["autonomy_level"] == "autonomous"

    autonomous_by_rogue = build_profile_from_agt_entries(
        [{"agent_did": "a1", "event_type": "rogue_detection", "action": "quarantine"}]
    )
    assert autonomous_by_rogue["autonomy_level"] == "autonomous"


def test_agent_count_distinct():
    entries = [
        {"agent_did": "a1", "event_type": "tool_invocation", "action": "allow"},
        {"agent_did": "a1", "event_type": "tool_invocation", "action": "allow"},
        {"agent_did": "a2", "event_type": "tool_invocation", "action": "allow"},
    ]
    profile = build_profile_from_agt_entries(entries)
    assert profile["agent_count"] == 2


def test_verify_chain_continuity_intact():
    intact, broken_at = verify_chain_continuity(FIXTURE_ENTRIES)
    assert intact is True
    assert broken_at is None


def test_verify_chain_continuity_detects_break():
    tampered = [dict(e) for e in FIXTURE_ENTRIES]
    tampered[2]["previous_hash"] = "not-hash2"
    intact, broken_at = verify_chain_continuity(tampered)
    assert intact is False
    assert broken_at == 2


def test_no_data_field_content_read():
    raw_entry = {
        "entry_id": "e1",
        "event_type": "tool_invocation",
        "agent_did": "a1",
        "action": "allow",
        "data": {"tool": "crm_lookup", "query": "super secret customer PII payload"},
        "previous_hash": "genesis",
        "entry_hash": "hash1",
    }
    normalized = _normalize_entry(raw_entry)
    for field in _FORBIDDEN_CONTENT_FIELDS:
        assert field not in normalized
    assert "data" not in normalized

    profile = build_profile_from_agt_entries([normalized])
    profile_text = json.dumps(profile)
    assert "super secret" not in profile_text
    assert "crm_lookup" not in profile_text


def test_parse_jsonl(tmp_path):
    audit_file = tmp_path / "audit_trail.jsonl"
    audit_file.write_text("\n".join(json.dumps(e) for e in FIXTURE_ENTRIES))
    entries = parse_agt_audit_trail(audit_file)
    assert len(entries) == 3
    assert entries[0]["entry_id"] == "e1"
    assert "data" not in entries[0]


def test_parse_json_list(tmp_path):
    audit_file = tmp_path / "audit_trail.json"
    audit_file.write_text(json.dumps(FIXTURE_ENTRIES))
    entries = parse_agt_audit_trail(audit_file)
    assert len(entries) == 3


def test_parse_entries_wrapper(tmp_path):
    audit_file = tmp_path / "export.json"
    audit_file.write_text(json.dumps({"entries": FIXTURE_ENTRIES, "metadata": {"count": 3}}))
    entries = parse_agt_audit_trail(audit_file)
    assert len(entries) == 3


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_agt_audit_trail(tmp_path / "does-not-exist.jsonl")


def test_profile_from_agt_end_to_end(tmp_path):
    audit_file = tmp_path / "audit_trail.jsonl"
    audit_file.write_text("\n".join(json.dumps(e) for e in FIXTURE_ENTRIES))
    profile = profile_from_agt(audit_file)
    assert profile["agent_count"] == 1
    assert profile["autonomy_level"] == "supervised"


def test_profile_from_agt_raises_on_broken_chain(tmp_path):
    tampered = [dict(e) for e in FIXTURE_ENTRIES]
    tampered[2]["previous_hash"] = "not-hash2"
    audit_file = tmp_path / "audit_trail.jsonl"
    audit_file.write_text("\n".join(json.dumps(e) for e in tampered))
    with pytest.raises(ValueError, match="continuity broken"):
        profile_from_agt(audit_file)
    # verify_chain=False should skip the check entirely.
    profile = profile_from_agt(audit_file, verify_chain=False)
    assert profile["agent_count"] == 1


def test_imports_without_agt_installed():
    import importlib

    mod = importlib.import_module("iris_agt")
    assert hasattr(mod, "profile_from_agt")
    assert hasattr(mod, "parse_agt_audit_trail")
    assert hasattr(mod, "verify_chain_continuity")
