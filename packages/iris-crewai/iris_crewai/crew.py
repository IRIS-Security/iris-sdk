"""IrisCrew — govern a multi-agent CrewAI crew with per-agent passports."""

from __future__ import annotations

from typing import Any, Dict, Optional

from iris_core.models.passport import AgentPassport

from iris_crewai._governance import AgentGovernor, build_compliance_report


class IrisCrew:
    """
    Wraps a CrewAI Crew and validates every agent has its own AgentPassport.

    Example:
        crew = IrisCrew.from_crew(
            Crew(agents=[researcher, writer], tasks=[...]),
            passports={"Researcher": researcher_passport, "Writer": writer_passport},
        )
        result = crew.kickoff(inputs={"topic": "AI governance"})
        report = crew.compliance_report()
    """

    def __init__(
        self,
        crew: Any,
        passports: Dict[str, AgentPassport],
        governors: Dict[str, AgentGovernor],
    ):
        self._crew = crew
        self._passports = passports
        self._governors = governors
        self._last_report: Optional[dict] = None

    @classmethod
    def from_crew(
        cls,
        crew: Any,
        passports: Dict[str, AgentPassport],
    ) -> "IrisCrew":
        cls._validate_passports(crew, passports)
        governors = cls._collect_governors(crew, passports)
        return cls(crew, passports, governors)

    @staticmethod
    def _validate_passports(crew: Any, passports: Dict[str, AgentPassport]) -> None:
        agent_roles = [agent.role for agent in crew.agents]
        missing = [role for role in agent_roles if role not in passports]
        if missing:
            raise ValueError(
                "Every agent in the crew must have an AgentPassport keyed by role name. "
                f"Missing passports for: {', '.join(missing)}"
            )

    @staticmethod
    def _collect_governors(
        crew: Any,
        passports: Dict[str, AgentPassport],
    ) -> Dict[str, AgentGovernor]:
        governors: Dict[str, AgentGovernor] = {}
        for agent in crew.agents:
            role = agent.role
            if hasattr(agent, "_iris_governor"):
                governors[role] = agent._iris_governor
            else:
                governors[role] = AgentGovernor(passports[role])
        return governors

    def kickoff(self, inputs: Optional[dict] = None, **kwargs: Any) -> Any:
        self._validate_passports(self._crew, self._passports)
        result = self._crew.kickoff(inputs=inputs, **kwargs)
        self._last_report = build_compliance_report(self._governors)
        return result

    def compliance_report(self) -> dict:
        """Return crew compliance summary with per-agent violation counts."""
        if self._last_report is not None:
            return self._last_report
        return build_compliance_report(self._governors)
