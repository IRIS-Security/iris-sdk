"""Patient summarizer after IRIS governance — one-line drop-in change."""

try:
    from iris_anthropic import IrisAnthropic
    from iris import AgentPassport, DataClassification, ComplianceTag
except ImportError:
    raise ImportError(
        "iris_anthropic is optional for this demo file. "
        "Install with: pip install iris-security-sdk[anthropic]"
    ) from None

passport = AgentPassport(
    name="meridian-patient-summarizer",
    owner="platform@meridianhealth.org",
    team="clinical-ai",
    data_classification=DataClassification.PHI,
    compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    is_high_risk_ai=True,
    allowed_regions=["us-east-1", "us-west-2"],
)

# One line change: anthropic.Anthropic() → IrisAnthropic()
client = IrisAnthropic(passport=passport)


def summarize_patient_record(patient_id: str, record: dict) -> str:
    """
    Now governed by IRIS:
    - PHI data classification enforced
    - Cross-region transfer blocked
    - Every call logged to Evidence Vault
    - Colorado AI Act transparency disclosure generated
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
