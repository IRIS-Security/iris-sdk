"""Ungoverned LangChain appointment scheduler — no consent gate, no audit trail."""

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

llm = ChatOpenAI(model="gpt-4o", temperature=0)


@tool
def lookup_patient(patient_id: str) -> dict:
    """Look up patient contact information."""
    return {"patient_id": patient_id, "name": "Jane Doe", "phone": "555-0100"}


@tool
def schedule_appointment(patient_id: str, provider_id: str, date: str) -> dict:
    """Schedule appointment — no consent gate, no audit trail."""
    return {"scheduled": True, "confirmation": "APT-12345", "date": date}


prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a medical appointment scheduling assistant."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

tools = [lookup_patient, schedule_appointment]
agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)


def book_appointment(patient_id: str, provider_id: str, date: str) -> dict:
    return executor.invoke({
        "input": f"Schedule appointment for patient {patient_id} with {provider_id} on {date}",
    })
