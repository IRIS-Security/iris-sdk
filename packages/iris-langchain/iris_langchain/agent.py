"""IrisLangChainAgent — wrap any LangChain agent with IRIS governance."""

from __future__ import annotations

import os
from typing import Any, List, Optional, Union

from iris_core.compliance.registry import ComplianceRegistry
from iris_core.models.passport import AgentPassport, ComplianceTag, Environment
from iris_core.models.policy import Severity, Violation

from iris_langchain.callback import IrisCallbackHandler


class IrisLangChainAgent:
    """
    Drop-in governance wrapper for LangChain AgentExecutor or Runnable agents.

    Example:
        agent = IrisLangChainAgent.from_agent(base_agent, passport)
        result = agent.run("Help this customer with their account")
    """

    def __init__(
        self,
        agent: Any,
        passport: AgentPassport,
        handler: IrisCallbackHandler,
        compliance_frameworks: Optional[List[str]] = None,
    ):
        self._agent = agent
        self.passport = passport
        self._handler = handler
        self._compliance_frameworks = compliance_frameworks or [
            t.value for t in passport.compliance_tags
        ]
        self._inject_callbacks()

    @classmethod
    def from_agent(
        cls,
        agent: Any,
        passport: AgentPassport,
        compliance: Optional[List[str]] = None,
        environment: Optional[str] = None,
    ) -> "IrisLangChainAgent":
        if compliance:
            passport.compliance_tags = [ComplianceTag(c) for c in compliance]
        env_name = environment or os.environ.get("IRIS_ENV", "dev")
        env = Environment(env_name)
        handler = IrisCallbackHandler(passport, env)
        return cls(agent, passport, handler, compliance_frameworks=compliance)

    def _inject_callbacks(self) -> None:
        if hasattr(self._agent, "callbacks"):
            existing = list(self._agent.callbacks or [])
            if self._handler not in existing:
                existing.append(self._handler)
            self._agent.callbacks = existing

    def _config_with_callbacks(self, config: Optional[dict] = None) -> dict:
        config = dict(config or {})
        callbacks = list(config.get("callbacks") or [])
        if self._handler not in callbacks:
            callbacks.append(self._handler)
        config["callbacks"] = callbacks
        return config

    def run(self, input: Union[str, dict], **kwargs: Any) -> Any:
        self._handler.begin_run()
        try:
            if hasattr(self._agent, "run"):
                callbacks = list(kwargs.pop("callbacks", None) or [])
                if self._handler not in callbacks:
                    callbacks.append(self._handler)
                result = self._agent.run(
                    input,
                    callbacks=callbacks or [self._handler],
                    **kwargs,
                )
            else:
                result = self.invoke(input, **kwargs)
            if not self._handler.current_run or not self._handler.current_run.finalized:
                self._handler.finalize_run(output=result)
            return result
        except Exception:
            if self._handler.current_run and not self._handler.current_run.finalized:
                self._handler.finalize_run()
            raise

    async def ainvoke(self, input: Union[str, dict], **kwargs: Any) -> Any:
        self._handler.begin_run()
        try:
            config = self._config_with_callbacks(kwargs.pop("config", None))
            payload = input if isinstance(input, dict) else {"input": input}
            if hasattr(self._agent, "ainvoke"):
                result = await self._agent.ainvoke(payload, config=config, **kwargs)
            else:
                raise TypeError("Wrapped agent does not support ainvoke()")
            if not self._handler.current_run or not self._handler.current_run.finalized:
                self._handler.finalize_run(output=result)
            return result
        except Exception:
            if self._handler.current_run and not self._handler.current_run.finalized:
                self._handler.finalize_run()
            raise

    def invoke(self, input: Union[str, dict], **kwargs: Any) -> Any:
        self._handler.begin_run()
        try:
            config = self._config_with_callbacks(kwargs.pop("config", None))
            payload = input if isinstance(input, dict) else {"input": input}
            if hasattr(self._agent, "invoke"):
                result = self._agent.invoke(payload, config=config, **kwargs)
            elif hasattr(self._agent, "run"):
                return self.run(input, **kwargs)
            else:
                raise TypeError("Wrapped agent does not support invoke() or run()")
            if not self._handler.current_run or not self._handler.current_run.finalized:
                self._handler.finalize_run(output=result)
            return result
        except Exception:
            if self._handler.current_run and not self._handler.current_run.finalized:
                self._handler.finalize_run()
            raise

    def compliance_check(self) -> List[Violation]:
        registry = ComplianceRegistry()
        return registry.check_passport(self.passport, self._compliance_frameworks)

    @property
    def is_ready_for_production(self) -> bool:
        violations = self.compliance_check()
        critical = [v for v in violations if v.severity == Severity.CRITICAL]
        return len(critical) == 0
