"""Resolve governance/ directory locations for local GitOps workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def find_governance_root(start: Optional[Path] = None) -> Path:
    """
    Find the governance root directory.

    Walks up from start (or cwd) looking for governance/. Falls back to
    ./governance relative to cwd when not found.
    """
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    for candidate in [current, *current.parents]:
        gov = candidate / "governance"
        if gov.is_dir():
            return gov

    return Path.cwd() / "governance"
