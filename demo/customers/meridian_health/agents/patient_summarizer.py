"""Ungoverned Anthropic agent accessing PHI — maximum drama for the demo."""

import os

try:
    import anthropic
except ImportError:
    raise ImportError(
        "anthropic is optional for this demo file. "
        "Install with: pip install iris-security-sdk[anthropic]"
    ) from None

# No IRIS governance — accesses PHI with no controls
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def summarize_patient_record(patient_id: str, record: dict) -> str:
    """
    Summarizes a patient medical record.
    WARNING: Accesses PHI with no HIPAA controls, no audit trail,
    no data classification, and no cross-region restrictions.
    """
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"Summarize this patient record: {record}",
        }],
    )
    return message.content[0].text
