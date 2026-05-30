# iris-langchain

IRIS governance for LangChain agents. Add Cedar policy enforcement and evidence logging in three lines — no agent rewrite required.

```python
from iris_langchain import IrisLangChainAgent
from iris import AgentPassport, ComplianceTag

passport = AgentPassport(
    name="support-agent",
    owner="team@company.com",
    compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    is_high_risk_ai=True,
)
agent = IrisLangChainAgent.from_agent(base_agent, passport)
result = agent.run("Help this customer with their account")
```

See `examples/governed_agent.py` for a full agent setup.
