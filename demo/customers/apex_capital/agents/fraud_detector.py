"""Ungoverned OpenAI fraud detector — no governance, no audit trail."""

import os

try:
    from openai import OpenAI
except ImportError:
    raise ImportError(
        "openai is optional for this demo file. "
        "Install with: pip install iris-security-sdk[openai]"
    ) from None

# No IRIS governance — accesses transaction data with no controls
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def detect_fraud(transaction_id: str, amount: float, merchant: str) -> dict:
    """
    Analyze a transaction for fraud indicators.
    WARNING: Consequential decision with no consent gate or audit trail.
    """
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "You are a fraud detection AI for Apex Capital.",
            },
            {
                "role": "user",
                "content": (
                    f"Transaction {transaction_id}: ${amount} at {merchant}. "
                    "Is this fraudulent? Respond with approved or blocked."
                ),
            },
        ],
    )
    decision = response.choices[0].message.content or "approved"
    return {"transaction_id": transaction_id, "decision": decision.strip().lower()}
