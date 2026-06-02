from iris import AgentPassport, ComplianceTag
from iris_gemini import IrisGemini

passport = AgentPassport(
    name="gemini-agent",
    owner="team@company.com",
    compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
)

# One-line change from: client = google.genai.Client()
client = IrisGemini(passport=passport)

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Analyze this customer complaint and suggest a response.",
)

print(response.text)
print("IRIS evaluated this call. Policy enforced. Evidence logged.")
