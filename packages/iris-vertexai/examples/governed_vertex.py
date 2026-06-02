from iris import AgentPassport, ComplianceTag
from iris_vertexai import IrisVertexAI

passport = AgentPassport(
    name="vertex-agent",
    owner="team@gov-agency.gov",
    compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    allowed_regions=["us-central1", "us-east1"],
)

iris_vertex = IrisVertexAI(
    passport=passport,
    project="my-gcp-project",
    location="us-central1",
)

model = iris_vertex.get_model("gemini-1.5-pro")
response = model.generate_content("Summarize this document.")
print(response.text)
