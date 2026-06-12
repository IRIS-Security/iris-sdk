"""IrisCrew — govern a multi-agent CrewAI crew with per-agent passports."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from iris_core.models.passport import AgentPassport, Environment

from iris import IrisViolationError
from iris_crewai._governance import AgentGovernor, build_compliance_report, resolve_environment

logger = logging.getLogger("iris.crewai")


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
        self._last_violations: list[IrisViolationError] = []

    @classmethod
    def from_crew(
        cls,
        crew: Any,
        passports: Dict[str, AgentPassport],
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
    ) -> "IrisCrew":
        from iris_core.dev_trust import print_dev_trust_message

        print_dev_trust_message()
        cls._validate_passports(crew, passports, strict=True)
        governors = cls._collect_governors(crew, passports, user_email, user_role)
        return cls(crew, passports, governors)

    @staticmethod
    def _validate_passports(
        crew: Any,
        passports: Dict[str, AgentPassport],
        *,
        strict: bool = True,
    ) -> None:
        agent_roles = [agent.role for agent in crew.agents]
        missing = [role for role in agent_roles if role not in passports]
        if not missing:
            return

        message = (
            "Every agent in the crew must have an AgentPassport keyed by role name. "
            f"Missing passports for: {', '.join(missing)}"
        )
        env = resolve_environment()
        if strict or env in (Environment.STAGING, Environment.PRODUCTION):
            raise ValueError(message)
        logger.warning(message)

    @staticmethod
    def _collect_governors(
        crew: Any,
        passports: Dict[str, AgentPassport],
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
    ) -> Dict[str, AgentGovernor]:
        governors: Dict[str, AgentGovernor] = {}
        for agent in crew.agents:
            role = agent.role
            if hasattr(agent, "_iris_governor"):
                governors[role] = agent._iris_governor
            else:
                governors[role] = AgentGovernor(
                    passports[role],
                    user_email=user_email,
                    user_role=user_role,
                )
        return governors

    def kickoff(self, inputs: Optional[dict] = None, **kwargs: Any) -> dict:
        """
        Run the governed crew.

        Returns a dict with ``result`` (crew output) and ``compliance`` summary.
        Compliance report is always generated, even when kickoff fails.
        """
        self._last_violations = []
        env = resolve_environment()
        self._validate_passports(self._crew, self._passports, strict=False)

        if env in (Environment.STAGING, Environment.PRODUCTION):
            missing = [
                role
                for role in (agent.role for agent in self._crew.agents)
                if role not in self._passports
            ]
            if missing:
                raise ValueError(
                    "Cannot kickoff crew in production without passports for all agents. "
                    f"Missing passports for: {', '.join(missing)}"
                )

        crew_result: Any = None
        try:
            crew_result = self._crew.kickoff(inputs=inputs, **kwargs)
        except IrisViolationError as exc:
            self._last_violations.append(exc)
            for violation in exc.result.violations:
                logger.error(
                    "IRIS violation during crew kickoff [%s]: %s",
                    violation.rule_id,
                    violation.message,
                )
        finally:
            self._last_report = build_compliance_report(self._governors)

        return {
            "result": crew_result,
            "compliance": self._last_report,
            "violations": [exc.result.decision for exc in self._last_violations],
        }

    def compliance_report(self) -> dict:
        """Return crew compliance summary with per-agent violation counts."""
        if self._last_report is not None:
            return self._last_report
        return build_compliance_report(self._governors)
