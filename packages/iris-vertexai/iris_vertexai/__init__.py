"""
IRIS Vertex AI integration - governed wrapper for Vertex AI GenerativeModel.
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

from iris_vertexai.client import IrisGenerativeModel, IrisVertexAI

__version__ = "0.1.0"

__all__ = [
    "IrisVertexAI",
    "IrisGenerativeModel",
    "IrisViolationError",
    "AgentPassport",
    "ComplianceTag",
    "DataClassification",
    "Environment",
    "Violation",
]
