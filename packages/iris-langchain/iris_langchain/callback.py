"""LangChain callback handler — IRIS policy at every tool and LLM step."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import UUID

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # pragma: no cover - graceful when langchain-core missing

    class BaseCallbackHandler:  # type: ignore[no-redef]
        """Stub when langchain-core is not installed."""

        pass


from iris_core.engine.cedar import CedarEngine
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport, Environment

from iris_langchain._governance import (
    RunSession,
    check_prompt_guardrails,
    detect_pii,
    enforce_result,
    evaluate_and_record,
    extract_regions,
    load_passport_policy,
    pii_output_violation,
    record_audit_event,
    resolve_environment,
    track_result,
)

if TYPE_CHECKING:
    from iris_core.models.policy import PolicyResult


class IrisCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback that evaluates every tool call against Cedar policy
    before execution and records evidence for audit.
    """

    def __init__(self, passport: AgentPassport, env: Optional[Environment] = None):
        super().__init__()
        self.passport = passport
        self.env = resolve_environment(env)
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id)
        load_passport_policy(self._engine, passport)
        self._pending_runs: Dict[UUID, str] = {}
        self._tool_results: Dict[UUID, "PolicyResult"] = {}
        self._current_run: Optional[RunSession] = None

    @property
    def current_run(self) -> Optional[RunSession]:
        return self._current_run

    @property
    def compliance_summary(self) -> Optional[dict]:
        if self._current_run is None:
            return None
        return self._current_run.to_summary()

    def begin_run(self, run_id: Optional[str] = None) -> str:
        """Start a new governed agent run with a unique Evidence Vault run_id."""
        session_id = run_id or str(uuid.uuid4())
        self._current_run = RunSession(run_id=session_id)
        record_audit_event(
            self._vault,
            run_id=self._current_run.run_id,
            event_type="run_start",
            resource=self.passport.name,
            details={"agent_id": self.passport.agent_id, "environment": self.env.value},
        )
        return self._current_run.run_id

    def finalize_run(self, output: Any = None) -> dict:
        """Write per-run compliance summary when agent_finish is not invoked."""
        if self._current_run is None:
            return {}
        if self._current_run.finalized:
            return self._current_run.to_summary()

        summary = self._current_run.to_summary()
        record_audit_event(
            self._vault,
            run_id=self._current_run.run_id,
            event_type="run_summary",
            resource=self.passport.name,
            details={"summary": summary, "final_output": str(output)[:2000] if output else None},
            decision="SUMMARY",
        )
        self._current_run.finalized = True
        return summary

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
        if self._current_run is not None:
            self._current_run.tool_calls += 1

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
            run_id=self._current_run.run_id if self._current_run else None,
        )
        self._tool_results[run_id] = result
        track_result(self._current_run, result)
        enforce_result(result, self.env)

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        tool_name = self._pending_runs.pop(run_id, "unknown")
        start_result = self._tool_results.pop(run_id, None)
        run_id_str = self._current_run.run_id if self._current_run else "unknown"

        record_audit_event(
            self._vault,
            run_id=run_id_str,
            event_type="tool_end",
            resource=tool_name,
            details={
                "output_preview": str(output)[:500],
                "start_decision": start_result.decision if start_result else None,
            },
        )

        output_text = str(output)
        if detect_pii(output_text):
            violation = pii_output_violation(self.passport, tool_name)
            if self._current_run is not None:
                self._current_run.pii_output_violations += 1
            record_audit_event(
                self._vault,
                run_id=run_id_str,
                event_type="pii_output_guardrail",
                resource=tool_name,
                details={"output_preview": output_text[:200]},
                violations=[violation],
                decision="VIOLATION" if self.env == Environment.PRODUCTION else "WARNING",
            )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        tool_name = self._pending_runs.pop(run_id, "unknown")
        self._tool_results.pop(run_id, None)
        run_id_str = self._current_run.run_id if self._current_run else "unknown"

        record_audit_event(
            self._vault,
            run_id=run_id_str,
            event_type="tool_error",
            resource=tool_name,
            details={
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
            decision="ERROR",
        )

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
        combined_prompt = "\n".join(prompts or [])
        guardrail_violations = check_prompt_guardrails(combined_prompt, self.passport)

        meta = metadata or {}
        data_region = meta.get("data_region")
        destination_region = meta.get("destination_region") or meta.get("dest_region")

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
            run_id=self._current_run.run_id if self._current_run else None,
            extra_violations=guardrail_violations,
        )
        track_result(self._current_run, result)
        enforce_result(result, self.env)

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        chain_name = serialized.get("name", serialized.get("id", "chain"))
        run_id_str = self._current_run.run_id if self._current_run else "unknown"
        record_audit_event(
            self._vault,
            run_id=run_id_str,
            event_type="chain_start",
            resource=str(chain_name),
            details={"input_keys": list(inputs.keys()) if inputs else []},
        )

    def on_agent_finish(
        self,
        finish: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        output = getattr(finish, "return_values", finish)
        if hasattr(output, "get"):
            output_text = output.get("output", str(output))
        else:
            output_text = str(output)

        run_id_str = self._current_run.run_id if self._current_run else "unknown"
        record_audit_event(
            self._vault,
            run_id=run_id_str,
            event_type="agent_finish",
            resource=self.passport.name,
            details={"output_preview": output_text[:2000]},
        )
        self.finalize_run(output=output_text)
