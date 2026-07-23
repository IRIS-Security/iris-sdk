"""Policy result and violation models shared across all IRIS packages."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Severity(str, Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


class Action(str, Enum):
    CALL    = "call"
    READ    = "read"
    WRITE   = "write"
    EXECUTE = "execute"
    DELETE  = "delete"


class RiskTier(str, Enum):
    """
    Risk-tier classification for a policy decision.

    Orthogonal to `decision` (PERMIT | DENY | PERMIT_WITH_WARNINGS) — this is
    not new enforcement vocabulary, just an honest label for what the existing
    fields already mean:
      AUTO_ALLOW — permitted, no human involved (the default for routine calls)
      STEP_UP    — permitted pending human approval (requires_hitl=True)
      AUTO_DENY  — blocked without bothering a human (decision == DENY)
    """
    AUTO_ALLOW = "auto_allow"
    STEP_UP = "step_up"
    AUTO_DENY = "auto_deny"


@dataclass
class Violation:
    rule_id: str
    severity: Severity
    message: str
    compliance_refs: List[str] = field(default_factory=list)
    remediation: str = ""

    def is_blocking(self, environment: str) -> bool:
        """
        Determine if this violation should block execution.
        Dev/test: only CRITICAL blocks. Staging/prod: HIGH+ blocks.
        """
        if environment in ("dev", "test"):
            return self.severity == Severity.CRITICAL
        return self.severity in (Severity.HIGH, Severity.CRITICAL)


@dataclass
class PolicyResult:
    decision: str                           # PERMIT | DENY | PERMIT_WITH_WARNINGS
    violations: List[Violation] = field(default_factory=list)
    agent_id: str = ""
    action: str = ""
    resource: str = ""
    environment: str = ""
    requires_hitl: bool = False
    hitl_rule: str = ""
    hitl_review_type: str = "business"
    compliance_hitl_violation: Optional[Violation] = None
    is_compliance_block: bool = False
    cedar_annotations: dict = field(default_factory=dict)
    inform_violations: List[Violation] = field(default_factory=list)
    drift_score: Optional[float] = None
    drift_flagged: bool = False
    aarm_r7: bool = False
    trust_state: Optional[str] = None
    trust_state_reason: Optional[str] = None

    @property
    def permitted(self) -> bool:
        return self.decision in ("PERMIT", "PERMIT_WITH_WARNINGS")

    @property
    def has_warnings(self) -> bool:
        return bool(self.violations) and self.decision == "PERMIT_WITH_WARNINGS"

    @property
    def risk_tier(self) -> RiskTier:
        if self.is_compliance_block or self.decision == "DENY":
            return RiskTier.AUTO_DENY
        if self.requires_hitl:
            return RiskTier.STEP_UP
        return RiskTier.AUTO_ALLOW
