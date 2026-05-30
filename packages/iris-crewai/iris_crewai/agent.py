"""IrisCrewAgent — wrap any CrewAI agent with IRIS governance."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from iris_core.models.passport import AgentPassport

from iris_crewai._governance import AgentGovernor, make_step_callback
from iris_crewai.tools import iris_crew_tool

_IRIS_CREW_AGENT_CLS: type | None = None


def _iris_crew_agent_class() -> type:
    global _IRIS_CREW_AGENT_CLS
    if _IRIS_CREW_AGENT_CLS is not None:
        return _IRIS_CREW_AGENT_CLS

    from crewai import Agent

    class _IrisCrewAgentImpl(Agent):
        """
        CrewAI Agent with per-agent IRIS governance.

        Tool calls are evaluated against the agent's AgentPassport before execution.
        step_callback records each step without altering crew output formatting.
        """

        def __init__(self, passport: AgentPassport, /, **crewai_agent_kwargs: Any):
            governor = AgentGovernor(passport)
            tools = crewai_agent_kwargs.get("tools")
            if tools:
                crewai_agent_kwargs["tools"] = _govern_tool_list(tools, passport, governor)

            user_cb = crewai_agent_kwargs.pop("step_callback", None)
            crewai_agent_kwargs["step_callback"] = make_step_callback(governor, user_cb)

            super().__init__(**crewai_agent_kwargs)
            object.__setattr__(self, "_iris_passport", passport)
            object.__setattr__(self, "_iris_governor", governor)

        @classmethod
        def from_crew_agent(cls, agent: Agent, passport: AgentPassport) -> "_IrisCrewAgentImpl":
            """Wrap an existing CrewAI Agent with IRIS governance."""
            kwargs = _agent_kwargs_from_instance(agent)
            return cls(passport, **kwargs)

    _IRIS_CREW_AGENT_CLS = _IrisCrewAgentImpl
    return _IRIS_CREW_AGENT_CLS


def _govern_tool_list(
    tools: List[Any],
    passport: AgentPassport,
    governor: AgentGovernor,
) -> List[Any]:
    governed = []
    for item in tools:
        if hasattr(item, "_iris_governor"):
            governed.append(item)
            continue
        wrapped = iris_crew_tool(item, passport, governor=governor)
        governed.append(wrapped)
    return governed


def _agent_kwargs_from_instance(agent: Any) -> Dict[str, Any]:
    fields = (
        "role",
        "goal",
        "backstory",
        "llm",
        "tools",
        "verbose",
        "allow_delegation",
        "max_iter",
        "max_rpm",
        "max_execution_time",
        "memory",
        "cache",
        "allow_code_execution",
        "respect_context_window",
        "max_retry_limit",
        "function_calling_llm",
        "embedder",
        "system_template",
        "prompt_template",
        "response_template",
        "use_system_prompt",
    )
    kwargs: Dict[str, Any] = {}
    for field in fields:
        value = getattr(agent, field, None)
        if value is not None:
            kwargs[field] = value
    return kwargs


class IrisCrewAgent:
    """
    Drop-in governed CrewAI agent — two lines per agent in a crew.

    Example:
        researcher = IrisCrewAgent(researcher_passport, role="Researcher", goal="...", ...)
    """

    def __new__(cls, passport: AgentPassport, **crewai_agent_kwargs: Any) -> Any:
        impl = _iris_crew_agent_class()
        return impl(passport, **crewai_agent_kwargs)

    @classmethod
    def from_crew_agent(cls, agent: Any, passport: AgentPassport) -> Any:
        impl = _iris_crew_agent_class()
        return impl.from_crew_agent(agent, passport)
