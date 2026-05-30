"""
Minimal two-agent CrewAI crew with IRIS governance.

Requires: pip install iris-crewai crewai[tools]
Set OPENAI_API_KEY before running.
"""

from __future__ import annotations

from crewai import Crew, Task
from crewai.tools import tool

from iris import AgentPassport, ComplianceTag
from iris_crewai import IrisCrew, IrisCrewAgent


@tool
def web_search(query: str, data_region: str = "us-east-1") -> str:
    """Search the web for information on a topic."""
    return f"Findings for '{query}' in {data_region}: AI governance is evolving rapidly."


@tool
def write_summary(content: str) -> str:
    """Write a polished summary from research notes."""
    return f"Summary: {content[:200]}"


def main() -> None:
    researcher_passport = AgentPassport(
        name="researcher-agent",
        owner="team@company.com",
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    )
    writer_passport = AgentPassport(
        name="writer-agent",
        owner="team@company.com",
        compliance_tags=[ComplianceTag.COLORADO_AI_ACT],
    )

    researcher = IrisCrewAgent(
        researcher_passport,
        role="Researcher",
        goal="Find accurate information on the assigned topic",
        backstory="You are a diligent research analyst.",
        tools=[web_search],
        verbose=True,
    )
    writer = IrisCrewAgent(
        writer_passport,
        role="Writer",
        goal="Produce a clear summary from research notes",
        backstory="You are an experienced technical writer.",
        tools=[write_summary],
        verbose=True,
    )

    research_task = Task(
        description="Research the topic: {topic}",
        expected_output="Bullet-point research notes",
        agent=researcher,
    )
    write_task = Task(
        description="Write a summary based on the research",
        expected_output="A concise paragraph",
        agent=writer,
        context=[research_task],
    )

    crew = IrisCrew.from_crew(
        Crew(agents=[researcher, writer], tasks=[research_task, write_task], verbose=True),
        passports={"Researcher": researcher_passport, "Writer": writer_passport},
    )

    result = crew.kickoff(inputs={"topic": "AI governance"})
    report = crew.compliance_report()

    print(result)
    print("Compliance report:", report)


if __name__ == "__main__":
    main()
