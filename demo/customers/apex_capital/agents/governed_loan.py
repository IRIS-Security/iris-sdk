"""Loan processor after IRIS governance — before/after comparison for demos."""

try:
    from langchain_openai import ChatOpenAI
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.tools import tool
except ImportError:
    raise ImportError(
        "langchain is optional for this demo file. "
        "Install with: pip install iris-security-sdk[langchain]"
    ) from None

try:
    from iris import IrisAgent, DataClassification
    from iris_langchain import IrisLangChainAgent
except ImportError:
    raise ImportError(
        "iris_langchain is optional for this demo file. "
        "Install with: pip install iris-security-sdk[langchain]"
    ) from None

agent_governance = IrisAgent(
    name="apex-loan-processor",
    owner="platform-team@apexcapital.com",
    team="ai-platform",
    data_classification=DataClassification.PII,
    compliance=["colorado-ai-act"],
    is_high_risk_ai=True,
    environment="dev",
)

llm = ChatOpenAI(model="gpt-4o", temperature=0)


@tool
def check_credit_score(applicant_id: str) -> dict:
    """Check the credit score for a loan applicant."""
    return {"score": 720, "risk": "low", "applicant_id": applicant_id}


@tool
def access_financial_records(applicant_id: str) -> dict:
    """Access financial records. Requires PII classification."""
    return {"annual_income": 85000, "existing_debt": 12000}


@tool
def make_loan_decision(applicant_id: str, amount: float, user_consent: bool = False) -> dict:
    """Make a loan decision. Requires user consent logged."""
    if not user_consent:
        raise ValueError("User consent must be logged before making a loan decision.")
    return {"decision": "approved", "amount": amount, "rate": 0.065}


prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a loan officer AI. Evaluate loan applications."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

tools = [check_credit_score, access_financial_records, make_loan_decision]
base_agent = create_tool_calling_agent(llm, tools, prompt)
base_executor = AgentExecutor(agent=base_agent, tools=tools, verbose=True)

governed_executor = IrisLangChainAgent.from_agent(base_executor, agent_governance.passport)


def process_loan_application(applicant_id: str, requested_amount: float) -> dict:
    result = governed_executor.run(
        f"Process loan application for {applicant_id} requesting ${requested_amount}",
    )
    return result


if __name__ == "__main__":
    violations = agent_governance.check_compliance(framework="colorado-ai-act")
    if violations:
        print("Compliance check FAILED:")
        for v in violations:
            print(f"  [{v.rule_id}] {v.message}")
    else:
        print("Compliance check PASSED — agent is Colorado AI Act compliant")
