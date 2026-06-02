"""Governed Vertex AI wrapper with IRIS policy enforcement."""

from __future__ import annotations

import importlib
import json
import os
import uuid
from datetime import datetime
from typing import Any, Optional

from iris import IrisViolationError
from iris_core.engine.cedar import CedarEngine, EvaluationContext
from iris_core.evidence.vault import EvidenceVault
from iris_core.models.passport import AgentPassport
from iris_core.models.policy import PolicyResult, Severity, Violation

from iris_vertexai.fedramp import check_fedramp_location, check_fedramp_model


def _lazy_vertexai():
    try:
        return importlib.import_module("vertexai")
    except ModuleNotFoundError as exc:
        raise ImportError(
            "google-cloud-aiplatform is required for IrisVertexAI. "
            "Install with: pip install google-cloud-aiplatform"
        ) from exc


def _lazy_vertexai_generative_models():
    try:
        return importlib.import_module("vertexai.generative_models")
    except ModuleNotFoundError as exc:
        raise ImportError(
            "vertexai.generative_models is unavailable. "
            "Install or upgrade: pip install google-cloud-aiplatform>=1.60"
        ) from exc


def _is_fedramp_enabled(passport: AgentPassport) -> bool:
    for tag in passport.compliance_tags:
        value = getattr(tag, "value", str(tag)).lower()
        if value == "fedramp":
            return True
    return False


def _load_passport_policy(engine: CedarEngine, passport: AgentPassport) -> None:
    if not passport.policy_ref:
        return
    from pathlib import Path

    policy_path = Path(passport.policy_ref)
    if not policy_path.is_absolute():
        policy_path = Path.cwd() / policy_path
    if policy_path.exists():
        engine.load_policy_file(passport.agent_id, policy_path)


def _current_environment():
    from iris_core.models.passport import Environment

    return Environment(os.environ.get("IRIS_ENV", "dev"))


def _enforce_result(result: PolicyResult) -> None:
    if result.decision == "DENY":
        raise IrisViolationError(result)


class IrisVertexAI:
    """Top-level Vertex AI client wrapper with governance-aware model creation."""

    def __init__(
        self,
        passport: AgentPassport,
        project: Optional[str] = None,
        location: Optional[str] = None,
        **kwargs: Any,
    ):
        evidence_vault_dir = kwargs.pop("evidence_vault_dir", None)
        vertexai = _lazy_vertexai()
        vertexai.init(project=project, location=location, **kwargs)
        self._passport = passport
        self._project = project
        self._location = location
        self._engine = CedarEngine()
        self._vault = EvidenceVault(agent_id=passport.agent_id, vault_dir=evidence_vault_dir)
        _load_passport_policy(self._engine, passport)

    def get_model(self, model_name: str) -> "IrisGenerativeModel":
        return IrisGenerativeModel(
            model_name=model_name,
            passport=self._passport,
            location=self._location,
            project=self._project,
            engine=self._engine,
            vault=self._vault,
        )


class IrisGenerativeModel:
    """Governed wrapper around vertexai.generative_models.GenerativeModel."""

    def __init__(
        self,
        model_name: str,
        passport: AgentPassport,
        location: Optional[str] = None,
        project: Optional[str] = None,
        engine: Optional[CedarEngine] = None,
        vault: Optional[EvidenceVault] = None,
    ):
        generative_models = _lazy_vertexai_generative_models()
        self._model_name = model_name
        self._passport = passport
        self._location = location
        self._project = project
        self._engine = engine or CedarEngine()
        self._vault = vault or EvidenceVault(agent_id=passport.agent_id)
        self._model = generative_models.GenerativeModel(model_name)

    def _record_with_metadata(
        self, ctx: EvaluationContext, result: PolicyResult, location_violations: list[Violation]
    ) -> None:
        entry = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "agent_id": self._passport.agent_id,
            "action": ctx.action,
            "resource": ctx.resource,
            "environment": ctx.environment.value,
            "decision": result.decision,
            "gcp_project": self._project,
            "gcp_location": self._location,
            "additional": {
                **ctx.additional,
                "gcp_project": self._project,
                "gcp_location": self._location,
            },
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity.value,
                    "message": v.message,
                    "compliance_refs": v.compliance_refs,
                }
                for v in (list(result.violations) + list(location_violations))
            ],
        }
        with open(self._vault._log_file, "a") as handle:
            handle.write(json.dumps(entry) + "\n")

    def _govern(self, action: str) -> None:
        env = _current_environment()
        violations: list[Violation] = []

        if self._location:
            if self._passport.allowed_regions and self._location not in self._passport.allowed_regions:
                violations.append(
                    Violation(
                        rule_id="IRIS-REGION-001",
                        severity=Severity.CRITICAL,
                        message=(
                            f"Location '{self._location}' is not in passport.allowed_regions."
                        ),
                        compliance_refs=["iris:region-policy"],
                        remediation=(
                            "Use an allowed location or update passport.allowed_regions "
                            "with security approval."
                        ),
                    )
                )
            if self._location.startswith("us-gov-"):
                violations.append(
                    Violation(
                        rule_id="IRIS-REGION-002",
                        severity=Severity.HIGH,
                        message=(
                            f"Location '{self._location}' is a restricted government region."
                        ),
                        compliance_refs=["fedramp:high:region-review"],
                        remediation=(
                            "Ensure FedRAMP High authorization is documented for this location."
                        ),
                    )
                )
        else:
            violations.append(
                Violation(
                    rule_id="IRIS-REGION-003",
                    severity=Severity.CRITICAL,
                    message="Vertex AI location is required but missing.",
                    compliance_refs=["iris:region-policy"],
                    remediation="Provide a valid Vertex AI location before calling the model.",
                )
            )

        if _is_fedramp_enabled(self._passport):
            fedramp_location_violation = check_fedramp_location(self._location or "")
            if fedramp_location_violation:
                violations.append(fedramp_location_violation)
            fedramp_model_violation = check_fedramp_model(self._model_name)
            if fedramp_model_violation:
                violations.append(fedramp_model_violation)

        ctx = EvaluationContext(
            agent_id=self._passport.agent_id,
            action=action,
            resource=f"vertexai/{self._model_name}",
            resource_type="api",
            environment=env,
            data_region=self._location,
            data_classification=self._passport.data_classification.value,
            additional={
                "model": self._model_name,
                "gcp_project": self._project,
                "gcp_location": self._location,
            },
        )
        result = self._engine.evaluate(self._passport, ctx)
        if violations:
            result = PolicyResult(
                decision="DENY",
                violations=list(result.violations) + violations,
                agent_id=result.agent_id,
                action=result.action,
                resource=result.resource,
                environment=result.environment,
            )

        self._record_with_metadata(ctx, result, [])
        _enforce_result(result)

    def generate_content(self, contents: Any, **kwargs: Any) -> Any:
        self._govern(action="generate_content")
        return self._model.generate_content(contents, **kwargs)

    def generate_content_stream(self, **kwargs: Any) -> Any:
        self._govern(action="generate_content_stream")
        return self._model.generate_content_stream(**kwargs)

    def start_chat(self) -> "IrisChatSession":
        return IrisChatSession(
            chat_session=self._model.start_chat(),
            model=self,
        )


class IrisChatSession:
    """Governed wrapper around Vertex AI chat sessions."""

    def __init__(self, chat_session: Any, model: IrisGenerativeModel):
        self._chat_session = chat_session
        self._model = model

    def send_message(self, content: Any, **kwargs: Any) -> Any:
        self._model._govern(action="chat.send_message")
        return self._chat_session.send_message(content, **kwargs)
