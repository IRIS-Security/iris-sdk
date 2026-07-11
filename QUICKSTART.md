# IRIS Quickstart

Get IRIS running locally and govern your first LLM call in minutes.

## Install

```bash
pip install iris-security-sdk iris-security-cli
```

## Connect to Claude (optional but recommended)

```bash
pip install "iris-security-sdk[mcp]"
```

Add to Claude Desktop config — see [docs/mcp/README.md](docs/mcp/README.md).

## First run

```bash
iris quickstart
```

## What's new

Version **0.2.0** — dynamic certify, MCP server, HITL, employment AI bundles, GitHub App.

## The fastest way to see IRIS in action

```bash
pip install iris-security-sdk iris-security-cli
iris quickstart
```

That is it. You will see IRIS find ungoverned agents,
declare a new agent, and certify compliance in under 2 minutes.
No API key required for the first run.

## Then point it at your own code

```bash
iris scan --discover --dir .
iris declare --name my-agent --owner you@company.com \
  --team your-team --compliance colorado-ai-act
iris framework suggest --agent my-agent
```

---

## The IRIS vocabulary

IRIS uses its own vocabulary because it solves a different problem than Terraform:

| | Terraform | IRIS |
|---|---|---|
| **Problem** | Manages what gets deployed (before runtime) | Governs what runs at runtime (during execution) |

- `iris declare` — you declare what the agent is allowed to do
- `iris compile` — IRIS compiles plain English to Cedar policy
- `iris preview` — IRIS shows risk impact before you apply changes
- `iris enforce` — IRIS confirms runtime enforcement is active
- `iris witness` — IRIS witnesses every decision in real time
- `iris certify` — IRIS certifies compliance to any framework
- `iris sentinel` — IRIS stands sentinel, alerting on any deviation

If you know Terraform: `iris preview` ≈ `terraform plan`.
But `iris enforce`, `iris witness`, `iris sentinel`, and `iris certify`
have no Terraform equivalent. These commands govern runtime behavior —
something Terraform was never designed to do.

Legacy aliases still work: `iris register`, `iris policy diff`, `iris watch`, `iris test`, `iris drift watch`.

---

## Manual setup (step by step)

### 1) Install

```bash
pip install iris-security-sdk iris-security-cli
```

Optional provider integrations:

```bash
pip install iris-security-sdk[anthropic]
pip install iris-security-sdk[openai]
pip install iris-security-sdk[google]
pip install iris-security-sdk[mistral]
pip install iris-security-sdk[groq]
pip install iris-security-sdk[litellm]
pip install iris-security-vertexai
pip install iris-security-sdk[all]
```

### 2) Declare an agent

```bash
iris declare \
  --name my-agent \
  --owner you@company.com \
  --team my-team \
  --compliance colorado-ai-act \
  --high-risk
```

Or run `iris declare` with no flags for the interactive wizard.

### 3) Discover applicable frameworks (free)

```bash
iris framework suggest --agent my-agent
```

This runs an offline questionnaire (TurboTax style) and recommends which
frameworks apply. IRIS saves your recommendations to:

```bash
~/.iris/framework-recommendations.json
```

Expected output:

```text
REQUIRED
✓ colorado-ai-act    FREE    Your agent makes consequential decisions for Colorado users. SB 24-205 applies.

RECOMMENDED
○ soc2               PRO     B2B enterprise customers will typically ask for SOC 2 Type II evidence.

NOT APPLICABLE
— gdpr                       No EU or non-US user footprint detected.

1 free framework available now.
1 frameworks require IRIS Pro.
Get IRIS Pro: iris license activate <your-key>
```

## LLM setup (pick one)

**Option 1 — API key (auto-detected):**

```bash
export ANTHROPIC_API_KEY=your-key   # Claude (recommended)
export OPENAI_API_KEY=your-key      # GPT-4o
export GOOGLE_API_KEY=your-key      # Gemini
export MISTRAL_API_KEY=your-key     # Mistral
export GROQ_API_KEY=your-key        # Llama (fastest, free tier)
```

**Option 2 — Any provider via LiteLLM:**

```bash
pip install iris-security-sdk[litellm]
iris compile --agent my-agent --litellm-model ollama/llama3.2
```

**Option 3 — Run locally with Ollama (free, no API key):**

```bash
brew install ollama && ollama pull llama3.2 && ollama serve
pip install iris-security-sdk[litellm]
iris compile --agent my-agent --litellm-model ollama/llama3.2
```

## 4) Compile policy, preview changes, and certify compliance

```bash
iris compile --agent my-agent
iris preview --agent my-agent
iris certify --framework colorado-ai-act --agent my-agent
iris enforce --agent my-agent
iris witness --agent my-agent
```

## 5) Use a drop-in governed client

```python
from iris import AgentPassport, ComplianceTag
from iris_gemini import IrisGemini

passport = AgentPassport(
    name="gemini-agent",
    owner="team@company.com",
    compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
)

# One-line replacement for google.genai.Client()
client = IrisGemini(passport=passport)

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Analyze this customer complaint and suggest a response.",
)
print(response.text)
```

`IRIS_ENV=dev` warns; `IRIS_ENV=production` blocks denied calls.

### Vertex AI option

```python
from iris import AgentPassport, ComplianceTag
from iris_vertexai import IrisVertexAI

passport = AgentPassport(
    name="vertex-agent",
    owner="team@gov-agency.gov",
    compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    allowed_regions=["us-central1", "us-east1"],
)

vertex = IrisVertexAI(
    passport=passport,
    project="my-gcp-project",
    location="us-central1",
)
model = vertex.get_model("gemini-1.5-pro")
response = model.generate_content("Summarize this document.")
print(response.text)
```
