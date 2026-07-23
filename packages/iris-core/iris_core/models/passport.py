"""
AgentPassport: the identity contract for every AI agent governed by IRIS.
Think of this as the agent's driver's license — it describes who the agent
is, what it is allowed to do, and under what conditions.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import uuid
import yaml
import json


def _load_hitl_config(spec: dict):
    from iris_core.hitl.models import HITLConfig

    hitl_data = spec.get("hitl")
    if not hitl_data:
        return None
    return HITLConfig.from_dict(hitl_data)


def _load_budget_config(spec: dict):
    from iris_core.cost.budget import BudgetConfig

    budget_data = spec.get("budget")
    if not budget_data:
        return None
    return BudgetConfig.from_dict(budget_data)


class Environment(str, Enum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PII = "pii"
    PHI = "phi"                  # HIPAA protected health info
    RESTRICTED = "restricted"    # highest sensitivity


class ComplianceTag(str, Enum):
    COLORADO_AI_ACT = "colorado-ai-act"
    COLORADO_AI_ACT_ORIGINAL = "colorado-ai-act-original"  # deprecated — SB 24-205
    COLORADO_CHATBOT = "colorado-chatbot"
    COLORADO_HEALTH_AI = "colorado-health-ai"
    COLORADO_MENTAL_HEALTH_AI = "colorado-mental-health-ai"
    GDPR = "gdpr"
    HIPAA = "hipaa"
    SOC2 = "soc2"
    NIST_AI_RMF = "nist-ai-rmf"
    FEDRAMP = "fedramp"
    CCPA = "ccpa"
    CCPA_ADMT = "ccpa-admt"
    CHINA_PIPL = "china-pipl"
    ILLINOIS_AI_VIDEO = "illinois-ai-video"
    NYC_LL144 = "nyc-ll144"
    PDPA = "pdpa"


@dataclass
class UserContext:
    """
    End-user identity for delegated agent actions.

    Passed when an agent acts on behalf of an authenticated user.
    IRIS factors this into policy evaluation and the Evidence Vault audit trail.
    """

    user_id: str
    user_email: Optional[str] = None
    user_role: Optional[str] = None
    delegated_scopes: List[str] = field(default_factory=list)
    consent_logged: bool = False
    consent_timestamp: Optional[str] = None
    session_id: Optional[str] = None
    idp_provider: Optional[str] = None

    @classmethod
    def from_params(
        cls,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        user_authenticated: Optional[bool] = None,
        delegated_scopes: Optional[List[str]] = None,
        consent_logged: bool = False,
        consent_timestamp: Optional[str] = None,
        session_id: Optional[str] = None,
        idp_provider: Optional[str] = None,
    ) -> "UserContext":
        """Resolve user context from explicit params or IRIS_* environment variables."""
        email = user_email if user_email is not None else os.environ.get("IRIS_USER_EMAIL")
        role = user_role if user_role is not None else os.environ.get("IRIS_USER_ROLE")
        uid = user_id if user_id is not None else os.environ.get("IRIS_USER_ID", "")
        if user_authenticated is not None:
            authenticated = user_authenticated
        else:
            authenticated = bool(email or uid)
        return cls(
            user_id=uid or (email or "anonymous"),
            user_email=email,
            user_role=role,
            delegated_scopes=list(delegated_scopes or []),
            consent_logged=consent_logged,
            consent_timestamp=consent_timestamp,
            session_id=session_id,
            idp_provider=idp_provider,
        )

    @property
    def user_authenticated(self) -> bool:
        return bool(self.user_email or self.user_id)

    def evaluation_fields(self) -> dict:
        return {
            "user_email": self.user_email,
            "user_role": self.user_role,
            "user_authenticated": self.user_authenticated,
            "user_consent_logged": self.consent_logged,
        }


@dataclass
class ToolPermission:
    """
    A declared permission for an agent to call a specific tool.
    If a tool is not declared here, IRIS blocks it at runtime.
    """
    tool_id: str
    description: str
    allowed_actions: List[str] = field(default_factory=list)
    data_classifications_allowed: List[DataClassification] = field(default_factory=list)
    requires_user_consent: bool = False
    environments: List[Environment] = field(default_factory=lambda: list(Environment))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "description": self.description,
            "allowed_actions": self.allowed_actions,
            "data_classifications_allowed": [d.value for d in self.data_classifications_allowed],
            "requires_user_consent": self.requires_user_consent,
            "environments": [e.value for e in self.environments],
        }


@dataclass
class AgentPassport:
    """
    The core identity document for an AI agent in the IRIS governance system.

    Every agent must have a passport before it can operate in staging or
    production. In dev and test, IRIS auto-drafts a passport and opens a
    PR to capture it in the GitOps repo.

    Analogous to a building permit — it describes what is allowed to be
    built, by whom, under what conditions, and in which jurisdiction.
    """

    # Identity
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    version: str = "0.1.0"
    description: str = ""

    # Ownership
    owner: str = ""
    team: str = ""
    contact_email: str = ""

    # Permissions
    tool_permissions: List[ToolPermission] = field(default_factory=list)
    data_classification: DataClassification = DataClassification.INTERNAL
    allowed_regions: List[str] = field(default_factory=list)
    allowed_model_tiers: List[str] = field(default_factory=list)
    allowed_models: List[str] = field(default_factory=list)

    # Compliance
    compliance_tags: List[ComplianceTag] = field(default_factory=list)
    environments: List[Environment] = field(default_factory=lambda: [Environment.DEV])

    # User RBAC (PRO tier — who may invoke this agent)
    allowed_user_roles: List[str] = field(default_factory=list)
    allowed_user_emails: List[str] = field(default_factory=list)
    require_user_authentication: bool = False

    # User delegation (agent acts on behalf of end users)
    user_delegation_enabled: bool = False
    allowed_delegation_scopes: List[str] = field(default_factory=list)
    require_user_consent_for_delegation: bool = True

    # Runtime
    policy_ref: Optional[str] = None       # path to policy.cedar in GitOps repo
    intent_ref: Optional[str] = None       # path to policy-intent.md
    evidence_vault_id: Optional[str] = None
    bias_audit_date: Optional[str] = None
    evidence_vault_retention_days: Optional[int] = None
    hitl_config: Optional["HITLConfig"] = None
    budget_config: Optional["BudgetConfig"] = None
    compliance_response_overrides: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None      # security engineer who approved
    is_high_risk_ai: bool = False          # Colorado AI Act: high-risk system flag

    def to_yaml(self) -> str:
        """Serialize to YAML for GitOps repo commit."""
        data = {
            "apiVersion": "iris.io/v1alpha1",
            "kind": "AgentPassport",
            "metadata": {
                "name": self.name,
                "agent_id": self.agent_id,
            },
            "spec": {
                "version": self.version,
                "description": self.description,
                "owner": self.owner,
                "team": self.team,
                "contact_email": self.contact_email,
                "data_classification": self.data_classification.value,
                "allowed_regions": self.allowed_regions,
                "allowed_model_tiers": self.allowed_model_tiers,
                "allowed_models": self.allowed_models,
                "compliance_tags": [t.value for t in self.compliance_tags],
                "environments": [e.value for e in self.environments],
                "tool_permissions": [t.to_dict() for t in self.tool_permissions],
                "allowed_user_roles": self.allowed_user_roles,
                "allowed_user_emails": self.allowed_user_emails,
                "require_user_authentication": self.require_user_authentication,
                "user_delegation_enabled": self.user_delegation_enabled,
                "allowed_delegation_scopes": self.allowed_delegation_scopes,
                "require_user_consent_for_delegation": self.require_user_consent_for_delegation,
                "policy_ref": self.policy_ref,
                "intent_ref": self.intent_ref,
                "is_high_risk_ai": self.is_high_risk_ai,
                "created_at": self.created_at.isoformat(),
            }
        }
        if self.evidence_vault_id:
            data["spec"]["evidence_vault_id"] = self.evidence_vault_id
        if self.bias_audit_date:
            data["spec"]["bias_audit_date"] = self.bias_audit_date
        if self.evidence_vault_retention_days is not None:
            data["spec"]["evidence_vault_retention_days"] = self.evidence_vault_retention_days
        if self.hitl_config:
            data["spec"]["hitl"] = self.hitl_config.to_dict()
        if self.budget_config:
            data["spec"]["budget"] = self.budget_config.to_dict()
        if self.compliance_response_overrides:
            data["spec"]["compliance_response_overrides"] = self.compliance_response_overrides
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "AgentPassport":
        """Deserialize from YAML GitOps file."""
        data = yaml.safe_load(yaml_str)
        spec = data.get("spec", {})
        meta = data.get("metadata", {})
        tool_permissions = [
            ToolPermission(
                tool_id=tool["tool_id"],
                description=tool.get("description", ""),
                allowed_actions=tool.get("allowed_actions", []),
                data_classifications_allowed=[
                    DataClassification(value)
                    for value in tool.get("data_classifications_allowed", [])
                ],
                requires_user_consent=tool.get("requires_user_consent", False),
                environments=[
                    Environment(value) for value in tool.get("environments", [])
                ]
                or list(Environment),
            )
            for tool in spec.get("tool_permissions", [])
        ]
        return cls(
            agent_id=meta.get("agent_id", str(uuid.uuid4())),
            name=meta.get("name", ""),
            version=spec.get("version", "0.1.0"),
            description=spec.get("description", ""),
            owner=spec.get("owner", ""),
            team=spec.get("team", ""),
            contact_email=spec.get("contact_email", ""),
            data_classification=DataClassification(spec.get("data_classification", "internal")),
            allowed_regions=spec.get("allowed_regions", []),
            allowed_model_tiers=spec.get("allowed_model_tiers", []),
            allowed_models=spec.get("allowed_models", []),
            compliance_tags=[ComplianceTag(t) for t in spec.get("compliance_tags", [])],
            environments=[Environment(e) for e in spec.get("environments", ["dev"])],
            tool_permissions=tool_permissions,
            allowed_user_roles=spec.get("allowed_user_roles", []),
            allowed_user_emails=spec.get("allowed_user_emails", []),
            require_user_authentication=spec.get("require_user_authentication", False),
            user_delegation_enabled=spec.get("user_delegation_enabled", False),
            allowed_delegation_scopes=spec.get("allowed_delegation_scopes", []),
            require_user_consent_for_delegation=spec.get(
                "require_user_consent_for_delegation", True
            ),
            policy_ref=spec.get("policy_ref"),
            intent_ref=spec.get("intent_ref"),
            evidence_vault_id=spec.get("evidence_vault_id"),
            bias_audit_date=spec.get("bias_audit_date"),
            evidence_vault_retention_days=spec.get("evidence_vault_retention_days"),
            is_high_risk_ai=spec.get("is_high_risk_ai", False),
            hitl_config=_load_hitl_config(spec),
            budget_config=_load_budget_config(spec),
            compliance_response_overrides=spec.get("compliance_response_overrides") or {},
            last_reviewed_at=(
                datetime.fromisoformat(spec["last_reviewed_at"])
                if spec.get("last_reviewed_at")
                else None
            ),
            reviewed_by=spec.get("reviewed_by"),
        )

    @property
    def compliance_tags_str(self) -> List[str]:
        return [t.value for t in self.compliance_tags]

    def is_compliant_for_env(self, env: Environment) -> bool:
        """Quick check: is this passport valid for the target environment?"""
        return env in self.environments

    def requires_colorado_compliance(self) -> bool:
        """
        Colorado AI Act (SB 26-189): covered ADMT systems must have
        transparency disclosures; impact assessments are best practice.
        """
        return (
            ComplianceTag.COLORADO_AI_ACT in self.compliance_tags
            or self.is_high_risk_ai
        )

    def has_feature(self, feature) -> bool:
        """Return True if the current license tier includes the feature."""
        from iris_core.entitlements import Entitlements

        return Entitlements().has(feature)
