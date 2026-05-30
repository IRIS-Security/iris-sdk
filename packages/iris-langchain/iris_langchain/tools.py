"""iris_tool_guard — Cedar-governed LangChain tools."""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from iris_core.engine.cedar import CedarEngine
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment

from iris_langchain._governance import (
    enforce_result,
    evaluate_and_record,
    extract_regions,
    load_passport_policy,
)


def iris_tool_guard(
    tool: Any,
    passport: AgentPassport,
    action: str = "call",
    environment: Optional[str] = None,
) -> Any:
    """
    Wrap a LangChain Tool or StructuredTool with IRIS policy evaluation.

    Example:
        safe_search = iris_tool_guard(search_tool, passport, action="call")
    """
    from langchain_core.tools import BaseTool, StructuredTool

    env = Environment(environment or os.environ.get("IRIS_ENV", "dev"))
    engine = CedarEngine()
    vault = EvidenceVault(agent_id=passport.agent_id)
    load_passport_policy(engine, passport)

    def _evaluate(inputs: Optional[dict]) -> None:
        data_region, destination_region = extract_regions(inputs)
        data_classification = None
        if inputs and inputs.get("data_classification") is not None:
            data_classification = str(inputs["data_classification"])
        result = evaluate_and_record(
            engine,
            vault,
            passport,
            env,
            action=action,
            resource=tool.name,
            resource_type="tool",
            data_region=data_region,
            destination_region=destination_region,
            data_classification=data_classification,
        )
        enforce_result(result)

    if isinstance(tool, StructuredTool):
        original = tool.func

        def guarded_func(*args: Any, **kwargs: Any) -> Any:
            inputs = kwargs if kwargs else (args[0] if args and isinstance(args[0], dict) else {})
            _evaluate(inputs if isinstance(inputs, dict) else None)
            return original(*args, **kwargs)

        return StructuredTool(
            name=tool.name,
            description=tool.description,
            func=guarded_func,
            args_schema=getattr(tool, "args_schema", None),
            return_direct=getattr(tool, "return_direct", False),
            verbose=getattr(tool, "verbose", False),
            handle_tool_error=getattr(tool, "handle_tool_error", False),
        )

    if isinstance(tool, BaseTool):
        original_run = tool._run

        def guarded_run(*args: Any, **kwargs: Any) -> Any:
            tool_input = args[0] if args else kwargs
            inputs = tool_input if isinstance(tool_input, dict) else None
            _evaluate(inputs)
            return original_run(*args, **kwargs)

        tool._run = guarded_run  # type: ignore[method-assign]
        return tool

    if callable(tool) and hasattr(tool, "name"):
        name = getattr(tool, "name", "tool")
        description = getattr(tool, "description", "")

        def guarded_callable(*args: Any, **kwargs: Any) -> Any:
            inputs = kwargs if kwargs else (args[0] if args and isinstance(args[0], dict) else None)
            _evaluate(inputs if isinstance(inputs, dict) else None)
            return tool(*args, **kwargs)

        return StructuredTool(name=name, description=description, func=guarded_callable)

    raise TypeError(
        "iris_tool_guard expects a langchain_core BaseTool, StructuredTool, or callable Tool."
    )
