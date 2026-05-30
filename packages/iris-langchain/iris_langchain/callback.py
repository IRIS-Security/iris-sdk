"""LangChain callback handler — IRIS policy at every tool and LLM step."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from iris_core.engine.cedar import CedarEngine
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment

from iris_langchain._governance import (
    enforce_result,
    evaluate_and_record,
    extract_regions,
    load_passport_policy,
)


class IrisCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback that evaluates every tool call against Cedar policy
    before execution and records evidence for audit.
    """

    def __init__(self, passport: AgentPassport, env: Environment):
        super().__init__()
        self.passport = passport
        self.env = env
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id)
        load_passport_policy(self._engine, passport)
        self._pending_runs: Dict[UUID, str] = {}

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        inputs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name", "unknown")
        self._pending_runs[run_id] = tool_name
        data_region, destination_region = extract_regions(inputs)
        data_classification = None
        if inputs:
            dc = inputs.get("data_classification")
            data_classification = str(dc) if dc is not None else None

        result = evaluate_and_record(
            self._engine,
            self._vault,
            self.passport,
            self.env,
            action="call",
            resource=tool_name,
            resource_type="tool",
            data_region=data_region,
            destination_region=destination_region,
            data_classification=data_classification,
            user_consent_logged=bool(inputs.get("user_consent_logged")) if inputs else False,
        )
        enforce_result(result)

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._pending_runs.pop(run_id, None)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._pending_runs.pop(run_id, None)

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Detect cross-region context from LLM invocation metadata."""
        meta = metadata or {}
        data_region = meta.get("data_region")
        destination_region = meta.get("destination_region") or meta.get("dest_region")
        if not data_region and not destination_region:
            return

        model_name = serialized.get("name", serialized.get("id", "llm"))
        result = evaluate_and_record(
            self._engine,
            self._vault,
            self.passport,
            self.env,
            action="invoke",
            resource=str(model_name),
            resource_type="llm",
            data_region=str(data_region) if data_region else None,
            destination_region=str(destination_region) if destination_region else None,
        )
        enforce_result(result)
