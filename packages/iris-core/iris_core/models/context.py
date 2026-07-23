"""Evaluation context for Cedar policy checks."""

from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from iris_core.dlp.types import DLPFinding
from iris_core.models.passport import Environment, UserContext

logger = logging.getLogger("iris.cedar")

_ENV_ENUM_TO_NAME = {
    Environment.DEV: "dev",
    Environment.TEST: "test",
    Environment.STAGING: "staging",
    Environment.PRODUCTION: "production",
}

_ENV_NAME_TO_ENUM = {v: k for k, v in _ENV_ENUM_TO_NAME.items()}


def resolve_environment_name(
    environment_name: Optional[str] = None,
    environment: Optional[Environment] = None,
    passport_env: Optional[str] = None,
) -> str:
    """Resolve the named environment for org policy lookup."""
    if environment_name:
        return environment_name
    iris_env = os.environ.get("IRIS_ENV")
    if iris_env:
        return iris_env
    if passport_env:
        return passport_env
    if environment is not None:
        warnings.warn(
            "EvaluationContext.environment enum is deprecated. "
            "Use environment_name or set IRIS_ENV instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        return _ENV_ENUM_TO_NAME.get(environment, "dev")
    return "dev"


def environment_enum_from_name(name: str) -> Environment:
    """Map a dynamic environment name to the legacy Environment enum when possible."""
    normalized = name.lower()
    if normalized in _ENV_NAME_TO_ENUM:
        return _ENV_NAME_TO_ENUM[normalized]
    if normalized.startswith("production"):
        return Environment.PRODUCTION
    if normalized.startswith("staging"):
        return Environment.STAGING
    if normalized in ("ci", "sandbox"):
        return Environment.TEST
    return Environment.DEV


@dataclass
class EvaluationContext:
    """
    The context passed to Cedar for every policy evaluation.
    Think of this as the full dossier the toll booth inspector reviews
    before deciding to let the car through.
    """

    agent_id: str
    action: str
    resource: str
    resource_type: str
    environment: Environment
    environment_name: Optional[str] = None
    data_region: Optional[str] = None
    destination_region: Optional[str] = None
    data_classification: Optional[str] = None
    user_consent_logged: bool = False
    user_email: Optional[str] = None
    user_role: Optional[str] = None
    user_authenticated: bool = False
    user_context: Optional[UserContext] = None
    is_delegated: bool = False
    dlp_prompt_findings: Optional[List[DLPFinding]] = None
    dlp_response_findings: Optional[List[DLPFinding]] = None
    model_id: Optional[str] = None
    model_tier: Optional[str] = None
    user_work_authorization: Optional[str] = None
    directive_status: Optional[str] = None
    hitl_approved: bool = False
    auto_fallback_applied: bool = False
    require_hitl: bool = False
    require_hitl_reason: Optional[str] = None
    additional: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.environment_name is None:
            iris_env = os.environ.get("IRIS_ENV")
            if iris_env:
                self.environment_name = iris_env
            else:
                self.environment_name = _ENV_ENUM_TO_NAME.get(self.environment, "dev")
                warnings.warn(
                    "EvaluationContext.environment enum is deprecated when "
                    "environment_name is unset. Set environment_name or IRIS_ENV.",
                    DeprecationWarning,
                    stacklevel=2,
                )
        else:
            self.environment = environment_enum_from_name(self.environment_name)

    @property
    def resolved_environment_name(self) -> str:
        return self.environment_name or resolve_environment_name(environment=self.environment)

    @property
    def tool_name(self) -> str:
        if self.additional.get("tool_name"):
            return str(self.additional["tool_name"])
        if self.resource_type == "tool":
            return self.resource
        return ""

    def to_cedar_context(self) -> Dict[str, Any]:
        return {
            "environment": self.resolved_environment_name,
            "data_region": self.data_region or "",
            "destination_region": self.destination_region or "",
            "data_classification": self.data_classification or "",
            "user_consent_logged": self.user_consent_logged,
            "user_email": self.user_email or "",
            "user_role": self.user_role or "",
            "user_authenticated": self.user_authenticated,
            "model_id": self.model_id or self.additional.get("model", ""),
            "model_tier": self.model_tier or "",
            "user_work_authorization": self.user_work_authorization or "",
            "directive_status": self.directive_status or "",
            "hitl_approved": self.hitl_approved,
            "auto_fallback_applied": self.auto_fallback_applied,
            **self.additional,
        }

    def to_dict(self) -> Dict[str, Any]:
        base = self.to_cedar_context()
        base.update(
            {
                "agent_id": self.agent_id,
                "action": self.action,
                "resource": self.resource,
                "resource_type": self.resource_type,
                "require_hitl": self.require_hitl,
                "tool_name": self.tool_name,
            }
        )
        return base
