"""
IRIS Gemini integration - one-line drop-in for google.genai.Client().
"""

from __future__ import annotations

from iris import IrisViolationError
from iris_core.models.passport import (
    AgentPassport,
    ComplianceTag,
    DataClassification,
    Environment,
)
from iris_core.models.policy import Violation

from iris_gemini.client import IrisGemini, IrisGeminiAsync
from iris_gemini.guardrails import scan_gemini_content

__version__ = "0.1.0"

__all__ = [
    "IrisGemini",
    "IrisGeminiAsync",
    "IrisViolationError",
    "AgentPassport",
    "ComplianceTag",
    "DataClassification",
    "Environment",
    "Violation",
    "scan_gemini_content",
]
