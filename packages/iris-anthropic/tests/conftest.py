"""Test fixtures — isolate Evidence Vault from the developer home directory."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def iris_home_tmp(monkeypatch, tmp_path):
    """Write ~/.iris evidence under pytest tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path))
