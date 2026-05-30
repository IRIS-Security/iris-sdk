"""iris_crew_tool — Cedar-governed CrewAI tools."""

from __future__ import annotations

from typing import Any, Callable, Optional

from iris_core.models.passport import AgentPassport, Environment

from iris_crewai._governance import AgentGovernor, enforce_result


def iris_crew_tool(
    tool_func: Any,
    passport: AgentPassport,
    action: str = "call",
    environment: Optional[str] = None,
    governor: Optional[AgentGovernor] = None,
) -> Any:
    """
    Wrap a CrewAI @tool-decorated function or Tool with IRIS policy evaluation.

    Preserves tool name, description, and args_schema metadata.

    Example:
        safe_search = iris_crew_tool(search_tool, passport, action="call")
    """
    env = Environment(environment) if environment else None
    active_governor = governor or AgentGovernor(passport, environment=env)

    def _evaluate(inputs: Optional[dict]) -> None:
        resource = _tool_resource_name(tool_func)
        result = active_governor.evaluate_tool(action=action, resource=resource, inputs=inputs)
        enforce_result(result)

    if _is_crewai_tool(tool_func):
        return _wrap_base_tool(tool_func, _evaluate)

    if callable(tool_func):
        decorated = _ensure_crew_tool(tool_func)
        return _wrap_base_tool(decorated, _evaluate)

    raise TypeError(
        "iris_crew_tool expects a crewai Tool/BaseTool instance or @tool-decorated callable."
    )


def _is_crewai_tool(obj: Any) -> bool:
    try:
        from crewai.tools.base_tool import BaseTool

        return isinstance(obj, BaseTool)
    except ImportError:
        return hasattr(obj, "name") and hasattr(obj, "run") and hasattr(obj, "func")


def _ensure_crew_tool(func: Callable[..., Any]) -> Any:
    if _is_crewai_tool(func):
        return func
    from crewai.tools import tool as crew_tool_decorator

    return crew_tool_decorator(func)


def _tool_resource_name(tool: Any) -> str:
    return getattr(tool, "name", getattr(tool, "__name__", "tool"))


def _normalize_inputs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Optional[dict]:
    if kwargs:
        return kwargs
    if args and isinstance(args[0], dict):
        return args[0]
    return None


def _wrap_base_tool(tool: Any, evaluate: Callable[[Optional[dict]], None]) -> Any:
    from crewai.tools.base_tool import Tool

    original_func = tool.func

    def guarded_func(*args: Any, **kwargs: Any) -> Any:
        evaluate(_normalize_inputs(args, kwargs))
        return original_func(*args, **kwargs)

    return Tool(
        name=tool.name,
        description=tool.description,
        func=guarded_func,
        args_schema=tool.args_schema,
        result_as_answer=getattr(tool, "result_as_answer", False),
        max_usage_count=getattr(tool, "max_usage_count", None),
    )
