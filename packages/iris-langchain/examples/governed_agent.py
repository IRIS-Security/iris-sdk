"""
Minimal LangChain agent with IRIS governance.

Requires optional deps: pip install iris-langchain[openai]
"""

from __future__ import annotations

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from iris import AgentPassport, ComplianceTag
from iris_langchain import IrisLangChainAgent


@tool
def lookup_account(account_id: str, data_region: str = "us-east-1") -> str:
    """Look up a customer account by ID."""
    return f"Account {account_id} in {data_region} is active."


def main() -> None:
    passport = AgentPassport(
        name="research-agent",
        owner="team@company.com",
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
        is_high_risk_ai=True,
        tool_permissions=[],  # declare tools in passport for production
    )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    tools = [lookup_account]
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are a helpful research agent."),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )
    agent_runnable = create_tool_calling_agent(llm, tools, prompt)
    base_executor = AgentExecutor(agent=agent_runnable, tools=tools, verbose=True)

    agent = IrisLangChainAgent.from_agent(
        base_executor,
        passport,
        compliance=["colorado-ai-act"],
    )
    result = agent.run("Research this topic and summarize findings")
    print(result)
    # IRIS evaluated every tool call. Violations blocked. Evidence logged.


if __name__ == "__main__":
    main()
