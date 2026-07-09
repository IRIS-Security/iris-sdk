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
