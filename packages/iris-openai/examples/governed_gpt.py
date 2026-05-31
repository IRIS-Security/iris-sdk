"""
Governed OpenAI — change one line, keep everything else identical.

Requires: pip install iris-openai
Set IRIS_ENV=dev (default) or production for fail-closed enforcement.
"""

from __future__ import annotations

from iris import AgentPassport, ComplianceTag, ToolPermission
from iris_openai import IrisOpenAI

passport = AgentPassport(
    name="analysis-agent",
    owner="team@company.com",
    compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    tool_permissions=[
        ToolPermission(tool_id="search", description="Web search", allowed_actions=["call"]),
    ],
)

# One line change from: client = openai.OpenAI()
client = IrisOpenAI(passport=passport)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Analyze this data."}],
)
print(response.choices[0].message.content)

search_tool = {
    "type": "function",
    "function": {
        "name": "search",
        "description": "Search the web",
        "parameters": {"type": "object", "properties": {}},
    },
}
payments_tool = {
    "type": "function",
    "function": {
        "name": "payments",
        "description": "Process payments",
        "parameters": {"type": "object", "properties": {}},
    },
}
email_tool = {
    "type": "function",
    "function": {
        "name": "email",
        "description": "Send email",
        "parameters": {"type": "object", "properties": {}},
    },
}

# IRIS filters to permitted tools; payments/email removed if not on passport
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Look up the account."}],
    tools=[search_tool, payments_tool, email_tool],
)
