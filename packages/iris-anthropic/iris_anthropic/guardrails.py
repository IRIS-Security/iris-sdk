"""Prompt guardrails for Anthropic API calls — scan-only, non-blocking."""

from __future__ import annotations

import re
from typing import List

from iris_core.models.passport import AgentPassport, DataClassification
from iris_core.models.policy import Severity, Violation

_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
_DOB = re.compile(
    r"\b(?:0[1-9]|1[0-2])[/-](?:0[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b"
)
_CROSS_REGION = re.compile(r"cn-north|china|beijing", re.IGNORECASE)
_HIGH_RISK_DOMAIN = re.compile(r"\b(loan|diagnosis|hiring)\b", re.IGNORECASE)


def check_prompt_for_violations(prompt: str, passport: AgentPassport) -> List[Violation]:
    """
    Scan prompt text for policy-relevant patterns.

    Returns violations without blocking — the caller merges them into evaluation.
    """
    if not prompt:
        return []

    violations: List[Violation] = []

    if _SSN.search(prompt) or _CREDIT_CARD.search(prompt) or _DOB.search(prompt):
        violations.append(
            Violation(
                rule_id="IRIS-DATA-001",
                severity=Severity.HIGH,
                message=(
                    f"Prompt for agent '{passport.name}' may contain PII "
                    f"(SSN, payment card, or date-of-birth pattern). "
                    f"Passport data classification is '{passport.data_classification.value}'."
                ),
                compliance_refs=[
                    "colorado-ai-act:impact-assessment",
                    "gdpr:data-minimization",
                ],
                remediation=(
                    "Remove sensitive identifiers from the prompt or update the agent "
                    "passport data_classification to match the data being processed."
                ),
            )
        )

    if _CROSS_REGION.search(prompt):
        violations.append(
            Violation(
                rule_id="IRIS-XR-001",
                severity=Severity.CRITICAL,
                message=(
                    f"Prompt for agent '{passport.name}' references restricted "
                    f"cross-region geography (China / cn-north)."
                ),
                compliance_refs=["china-pipl:cross-border-transfer"],
                remediation=(
                    "Remove cross-region references from the prompt or document an "
                    "approved exception with your security engineer."
                ),
            )
        )

    if _HIGH_RISK_DOMAIN.search(prompt):
        violations.append(
            Violation(
                rule_id="CO-004",
                severity=Severity.HIGH,
                message=(
                    f"Prompt for agent '{passport.name}' references a high-risk "
                    f"consequential domain (loan, diagnosis, or hiring). "
                    f"Consumer opt-out and consent may be required under SB 24-205."
                ),
                compliance_refs=["colorado-ai-act:sb-24-205:consumer-opt-out"],
                remediation=(
                    "Set user_consent_logged=True in policy context for consequential "
                    "actions, or run 'iris compliance assess --agent "
                    f"{passport.agent_id} --framework colorado-ai-act'."
                ),
            )
        )

    return violations


def prompt_suggests_pii(prompt: str) -> bool:
    """Whether guardrails detected PII patterns (used to elevate data_classification)."""
    if not prompt:
        return False
    return bool(_SSN.search(prompt) or _CREDIT_CARD.search(prompt) or _DOB.search(prompt))


def effective_data_classification(prompt: str, passport: AgentPassport) -> str:
    if prompt_suggests_pii(prompt):
        return DataClassification.PII.value
    return passport.data_classification.value
