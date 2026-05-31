"""
Minimal IRIS + Anthropic integration — one line changes from the stock SDK.

Replace:
    client = anthropic.Anthropic()
With:
    client = IrisAnthropic(passport=passport)

All other Anthropic usage stays the same.
"""

from iris import AgentPassport, ComplianceTag
from iris_anthropic import IrisAnthropic

passport = AgentPassport(
    name="support-agent",
    owner="team@company.com",
    compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    is_high_risk_ai=False,
)

client = IrisAnthropic(passport=passport)

message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Help this customer."}],
)

# IRIS evaluated this call. Policy enforced. Evidence logged.
print(message.content[0].text)
