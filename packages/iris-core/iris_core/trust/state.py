"""Local trust-state model — a rolling-window read on an agent's governance
signals. Recomputed fresh on every check from the Evidence Vault, not a
persisted state machine (same idiom as the Phase 6b daily-budget check
recomputing from CostTracker.get_summary(since=...))."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class TrustState(str, Enum):
    TRUSTED = "trusted"
    DEGRADED = "degraded"
    SUSPECT = "suspect"


_SEVERITY_ORDER = {TrustState.TRUSTED: 0, TrustState.DEGRADED: 1, TrustState.SUSPECT: 2}


def is_worse(a: TrustState, b: TrustState) -> bool:
    """True if trust state `a` is a worse (more distrusted) state than `b`."""
    return _SEVERITY_ORDER[a] > _SEVERITY_ORDER[b]


@dataclass
class TrustStateConfig:
    """Per-agent trust-state configuration. Stored in passport.yaml (spec.trust).

    A rolling-window tally, not a persisted state machine: no "recovery"
    counter is needed because events simply age out of lookback_hours.
    """

    enabled: bool = False
    lookback_hours: int = 24
    degrade_after_violations: int = 3
    suspect_after_violations: int = 8
    degrade_after_hitl_denials: int = 2

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "TrustStateConfig":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            lookback_hours=int(data.get("lookback_hours", 24)),
            degrade_after_violations=int(data.get("degrade_after_violations", 3)),
            suspect_after_violations=int(data.get("suspect_after_violations", 8)),
            degrade_after_hitl_denials=int(data.get("degrade_after_hitl_denials", 2)),
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "lookback_hours": self.lookback_hours,
            "degrade_after_violations": self.degrade_after_violations,
            "suspect_after_violations": self.suspect_after_violations,
            "degrade_after_hitl_denials": self.degrade_after_hitl_denials,
        }


@dataclass
class TrustStateResult:
    state: TrustState
    reason: str
    violation_count: int
    hitl_denial_count: int


def compute_trust_state(
    agent_id: str,
    config: TrustStateConfig,
    vault=None,
) -> TrustStateResult:
    """Tally HIGH/CRITICAL violations and rejected HITL reviews within
    config.lookback_hours and bucket the result against config's thresholds."""
    if vault is None:
        from iris_core.evidence.vault import EvidenceVault

        vault = EvidenceVault(agent_id=agent_id)

    # EvidenceVault stamps entries with naive datetime.utcnow().isoformat();
    # match that format exactly so the string comparison in get_events()
    # compares like-for-like (a tz-aware "+00:00" suffix would break it).
    since = (datetime.utcnow() - timedelta(hours=config.lookback_hours)).isoformat()
    events = vault.get_events(limit=1000, since=since)

    violation_count = sum(
        1
        for event in events
        for v in event.get("violations", [])
        if v.get("severity") in ("HIGH", "CRITICAL")
    )
    hitl_denial_count = sum(
        1
        for event in events
        if event.get("event_type") == "hitl_resolved" and event.get("status") == "rejected"
    )

    if violation_count >= config.suspect_after_violations:
        state = TrustState.SUSPECT
        reason = (
            f"{violation_count} HIGH/CRITICAL violations in the last "
            f"{config.lookback_hours}h exceeds suspect threshold "
            f"({config.suspect_after_violations}) (passport.trust.suspect_after_violations)"
        )
    elif violation_count >= config.degrade_after_violations:
        state = TrustState.DEGRADED
        reason = (
            f"{violation_count} HIGH/CRITICAL violations in the last "
            f"{config.lookback_hours}h exceeds degrade threshold "
            f"({config.degrade_after_violations}) (passport.trust.degrade_after_violations)"
        )
    elif hitl_denial_count >= config.degrade_after_hitl_denials:
        state = TrustState.DEGRADED
        reason = (
            f"{hitl_denial_count} rejected HITL reviews in the last "
            f"{config.lookback_hours}h exceeds degrade threshold "
            f"({config.degrade_after_hitl_denials}) (passport.trust.degrade_after_hitl_denials)"
        )
    else:
        state = TrustState.TRUSTED
        reason = (
            f"{violation_count} violations, {hitl_denial_count} HITL denials "
            f"in the last {config.lookback_hours}h — within configured thresholds"
        )

    return TrustStateResult(
        state=state,
        reason=reason,
        violation_count=violation_count,
        hitl_denial_count=hitl_denial_count,
    )
