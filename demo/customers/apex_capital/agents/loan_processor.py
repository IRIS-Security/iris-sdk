"""Ungoverned LangChain loan processor — deliberately bad for IRIS discovery demo."""

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

# No IRIS governance — this is what we are about to fix
llm = ChatOpenAI(model="gpt-4o", temperature=0)


@tool
def check_credit_score(applicant_id: str) -> dict:
    """Check the credit score for a loan applicant."""
    return {"score": 720, "risk": "low", "applicant_id": applicant_id}


@tool
def access_financial_records(applicant_id: str) -> dict:
    """Access detailed financial records including SSN and account numbers."""
    return {
        "ssn": "XXX-XX-1234",
        "annual_income": 85000,
        "existing_debt": 12000,
        "applicant_id": applicant_id,
    }


@tool
def make_loan_decision(applicant_id: str, amount: float) -> dict:
    """Make a final loan approval or denial decision."""
    return {"decision": "approved", "amount": amount, "rate": 0.065}


prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a loan officer AI. Evaluate loan applications."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

tools = [check_credit_score, access_financial_records, make_loan_decision]
agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)


def process_loan_application(applicant_id: str, requested_amount: float) -> dict:
    result = executor.invoke({
        "input": f"Process loan application for {applicant_id} requesting ${requested_amount}",
    })
    return result
