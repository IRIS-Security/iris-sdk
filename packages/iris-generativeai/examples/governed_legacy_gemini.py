from iris import AgentPassport, ComplianceTag
from iris_generativeai import IrisGenerativeAI

passport = AgentPassport(
    name="legacy-gemini-agent",
    owner="team@company.com",
    compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
)

iris_genai = IrisGenerativeAI(passport=passport)
model = iris_genai.GenerativeModel("gemini-1.5-pro")
response = model.generate_content("Help this customer.")

print(response.text)
