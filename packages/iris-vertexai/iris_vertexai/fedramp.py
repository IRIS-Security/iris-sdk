"""FedRAMP-specific governance checks for Vertex AI integrations."""

from __future__ import annotations

from typing import Optional

from iris_core.models.policy import Severity, Violation

FEDRAMP_AUTHORIZED_VERTEX_REGIONS = {
    "us-central1",
    "us-east1",
    "us-east4",
    "us-west1",
    "us-west2",
    "us-west3",
    "us-west4",
    "us-south1",
}

FEDRAMP_AUTHORIZED_VERTEX_MODELS = {
    "gemini-1.5-pro",
    "gemini-1.5-flash",
}


def check_fedramp_location(location: str) -> Optional[Violation]:
    """Return violation when Vertex AI location is not FedRAMP-authorized."""
    normalized = (location or "").strip().lower()
    if not normalized:
        return Violation(
            rule_id="FEDRAMP-001",
            severity=Severity.CRITICAL,
            message="FedRAMP location is missing for this Vertex AI request.",
            compliance_refs=["fedramp:moderate:residency"],
            remediation=(
                "Set a FedRAMP-authorized Vertex AI region and retry the request."
            ),
        )

    if normalized in FEDRAMP_AUTHORIZED_VERTEX_REGIONS:
        return None

    if normalized.startswith("us-gov-"):
        return Violation(
            rule_id="FEDRAMP-001",
            severity=Severity.CRITICAL,
            message=(
                f"Location '{location}' requires additional FedRAMP High authorization."
            ),
            compliance_refs=["fedramp:high:authorization-boundary"],
            remediation=(
                "Obtain documented FedRAMP High authorization for this region "
                "or use an authorized FedRAMP Moderate region."
            ),
        )

    return Violation(
        rule_id="FEDRAMP-001",
        severity=Severity.CRITICAL,
        message=(
            f"Location '{location}' is not in the FedRAMP-authorized Vertex AI region list."
        ),
        compliance_refs=["fedramp:moderate:residency"],
        remediation=(
            "Use one of the authorized regions: "
            + ", ".join(sorted(FEDRAMP_AUTHORIZED_VERTEX_REGIONS))
            + "."
        ),
    )


def check_fedramp_model(model_name: str) -> Optional[Violation]:
    """Return violation when Vertex AI model authorization cannot be verified."""
    normalized = (model_name or "").strip().lower()
    if normalized in FEDRAMP_AUTHORIZED_VERTEX_MODELS:
        return None

    return Violation(
        rule_id="FEDRAMP-002",
        severity=Severity.HIGH,
        message=(
            f"Model '{model_name}' is not on the current FedRAMP-authorized Vertex AI list."
        ),
        compliance_refs=["fedramp:ai-workload:authorization"],
        remediation=(
            "Use a known authorized model (gemini-1.5-pro or gemini-1.5-flash) "
            "or complete an authorization review for this model."
        ),
    )
