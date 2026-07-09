# Copyright 2024-2025 Gilbert Martin / IRIS Security, Inc.

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from iris.scan import detect_workload


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text(
        "openai>=1.0\nlangchain>=0.2\n",
        encoding="utf-8",
    )
    app = tmp_path / "app.py"
    app.write_text(
        """
import openai
from langchain_openai import ChatOpenAI

model = ChatOpenAI(model="gpt-4o")
client = openai.OpenAI()

class UserSchema:
    ssn = "social_security"
    email_address = "test@example.com"
""",
        encoding="utf-8",
    )
    return tmp_path


def test_detect_workload_finds_openai_and_langchain(sample_project: Path):
    profile = detect_workload(str(sample_project))
    assert "openai" in profile["providers"]
    assert "langchain" in profile["frameworks"]
    assert any("gpt" in m for m in profile["models"])
    assert "pii" in profile["data_categories"]


def test_detect_workload_offline_no_network(sample_project: Path):
    def fail_socket(*args, **kwargs):
        raise AssertionError("Network call attempted during offline scan")

    with patch("socket.socket", side_effect=fail_socket):
        profile = detect_workload(str(sample_project))
    assert profile["source"] == "sdk_scan"


# Regression coverage for the dogfood false positive: detect_workload() used
# to flag data_categories=[biometric, financial, phi, pii] when scanning a
# governance/compliance tool's own source, because that source legitimately
# talks *about* those categories (DataClassification enum members, framework
# names like HIPAA/PCI, questionnaire copy, AgentPassport/passport.yaml
# vocabulary) without ever handling real data of that kind. apps/iris-cli/ in
# this repo is exactly that kind of codebase, so scanning it is the natural
# regression fixture.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_IRIS_CLI_ROOT = _REPO_ROOT / "apps" / "iris-cli"


@pytest.mark.skipif(not _IRIS_CLI_ROOT.is_dir(), reason="apps/iris-cli not present in this checkout")
def test_detect_workload_does_not_flag_own_compliance_vocabulary():
    profile = detect_workload(str(_IRIS_CLI_ROOT))
    assert profile["data_categories"] == []


@pytest.mark.skipif(not _IRIS_CLI_ROOT.is_dir(), reason="apps/iris-cli not present in this checkout")
def test_detect_workload_does_not_flag_iris_python_own_source():
    iris_python_root = Path(__file__).resolve().parents[1]
    profile = detect_workload(str(iris_python_root))
    assert profile["data_categories"] == []


def test_detect_workload_ignores_vocabulary_in_keyword_lists_and_prose(tmp_path: Path):
    (tmp_path / "linter.py").write_text(
        '''
"""Detects high-risk domains in someone else's code."""

high_risk_keywords = ["loan", "credit", "insurance", "medical", "diagnosis"]

QUESTIONS = [
    "Yes -- biometric or sensitive data",
    "HIPAA (healthcare)",
    "PCI DSS (payment cards)",
]

def load_passport(agent):
    passport = (agent / "passport.yaml").read_text()
    return passport
''',
        encoding="utf-8",
    )
    profile = detect_workload(str(tmp_path))
    assert profile["data_categories"] == []


def test_detect_workload_still_flags_real_field_assignment(tmp_path: Path):
    (tmp_path / "models.py").write_text(
        '''
class Patient:
    patient_id: str
    diagnosis = ""

record = {"credit_card": "4111111111111111", "fingerprint": template}
''',
        encoding="utf-8",
    )
    profile = detect_workload(str(tmp_path))
    assert set(profile["data_categories"]) == {"phi", "financial", "biometric"}


def test_detect_workload_skips_data_category_matches_in_test_files(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fixture.py").write_text(
        'ssn = "123-45-6789"\ncredit_card = "4111111111111111"\n',
        encoding="utf-8",
    )
    profile = detect_workload(str(tmp_path))
    assert profile["data_categories"] == []


def test_detect_workload_skips_data_category_matches_in_demo_files(tmp_path: Path):
    """Regression for the public iris-sdk repo's bundled demo/ tree: it
    intentionally simulates an "ungoverned agent" with realistic-looking
    field names to teach a sales demo — that's not evidence the SDK itself
    handles real customer PII/PHI."""
    demo_dir = tmp_path / "demo" / "customers" / "meridian_health" / "agents"
    demo_dir.mkdir(parents=True)
    (demo_dir / "patient_summarizer.py").write_text(
        'def summarize_patient_record(patient_id: str, record: dict) -> str:\n'
        '    return record.get("ssn")\n',
        encoding="utf-8",
    )
    profile = detect_workload(str(tmp_path))
    assert profile["data_categories"] == []
