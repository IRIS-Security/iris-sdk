"""Guardrail scanning for Gemini contents payloads."""

from __future__ import annotations

import re
from typing import Any, List

from iris_core.models.passport import AgentPassport
from iris_core.models.policy import Severity, Violation

_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
_DOB = re.compile(
    r"\b(?:0[1-9]|1[0-2])[/-](?:0[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b"
)
_CROSS_REGION = re.compile(r"cn-north|china|beijing", re.IGNORECASE)
_HIGH_RISK_DOMAIN = re.compile(r"\b(loan|diagnosis|hiring)\b", re.IGNORECASE)


def _extract_text(contents: Any) -> List[str]:
    if contents is None:
        return []
    if isinstance(contents, str):
        return [contents]
    if isinstance(contents, dict):
        values: List[str] = []
        for key in ("text", "content"):
            value = contents.get(key)
            if isinstance(value, str):
                values.append(value)
            elif value is not None:
                values.extend(_extract_text(value))
        if not values:
            for value in contents.values():
                values.extend(_extract_text(value))
        return values
    if isinstance(contents, (list, tuple)):
        values: List[str] = []
        for item in contents:
            values.extend(_extract_text(item))
        return values

    text = getattr(contents, "text", None)
    if isinstance(text, str):
        return [text]
    content = getattr(contents, "content", None)
    if content is not None:
        return _extract_text(content)
    return []


def scan_gemini_content(contents: Any, passport: AgentPassport) -> List[Violation]:
    """Scan Gemini request contents and return policy violations."""
    prompt = "\n".join(_extract_text(contents))
    if not prompt:
        return []

    violations: List[Violation] = []

    if _SSN.search(prompt) or _CREDIT_CARD.search(prompt) or _DOB.search(prompt):
        violations.append(
            Violation(
                rule_id="IRIS-DATA-001",
                severity=Severity.HIGH,
                message=(
                    f"Gemini prompt for agent '{passport.name}' may contain PII "
                    "(SSN, payment card, or date-of-birth pattern)."
                ),
                compliance_refs=[
                    "colorado-ai-act:impact-assessment",
                    "gdpr:data-minimization",
                ],
                remediation=(
                    "Remove sensitive identifiers from contents or update the "
                    "passport data_classification before this call."
                ),
            )
        )

    if _CROSS_REGION.search(prompt):
        violations.append(
            Violation(
                rule_id="IRIS-XR-001",
                severity=Severity.CRITICAL,
                message=(
                    f"Gemini prompt for agent '{passport.name}' references "
                    "restricted cross-region geography (China / cn-north)."
                ),
                compliance_refs=["china-pipl:cross-border-transfer"],
                remediation=(
                    "Remove cross-region references from contents or document an "
                    "approved exception with security."
                ),
            )
        )

    if _HIGH_RISK_DOMAIN.search(prompt):
        violations.append(
            Violation(
                rule_id="CO-004",
                severity=Severity.HIGH,
                message=(
                    f"Gemini prompt for agent '{passport.name}' references a "
                    "high-risk consequential domain (loan, diagnosis, or hiring)."
                ),
                compliance_refs=["colorado-ai-act:sb-24-205:consumer-opt-out"],
                remediation=(
                    "Set consent evidence in policy context for consequential "
                    "processing, or run an IRIS compliance assessment."
                ),
            )
        )

    return violations
