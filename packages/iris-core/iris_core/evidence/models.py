"""Evidence Vault v2 data model — append-only ledger entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class EvidenceEvent(BaseModel):
    """
    One immutable fact. Never updated after creation. Every other
    entity in the vault is derived from a collection of these.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    event_type: str
    agent_id: str
    agent_name: str
    environment: str
    timestamp: str
    sequence_number: int
    payload: Dict[str, Any]
    payload_hash: str
    signature: str
    prev_event_hash: str
    pii_redacted: bool = True

    def to_storage_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_storage_dict(cls, data: dict) -> "EvidenceEvent":
        return cls.model_validate(data)


@dataclass
class EvidenceChain:
    """
    A computed view, NOT separately persisted as authoritative —
    it's a materialized index over EvidenceEvent for fast querying.
    """

    chain_id: str
    chain_type: str
    event_ids: List[str]
    started_at: str
    completed_at: Optional[str]
    status: str

    @staticmethod
    def rebuild_from_events(events: List[EvidenceEvent]) -> List["EvidenceChain"]:
        """Reconstruct HITL and rotation chains from raw events."""
        hitl_by_review: Dict[str, List[EvidenceEvent]] = {}
        rotation_by_key: Dict[str, List[EvidenceEvent]] = {}

        for event in sorted(events, key=lambda e: e.sequence_number):
            if event.event_type == "hitl_requested":
                review_id = event.payload["review_id"]
                hitl_by_review.setdefault(review_id, []).append(event)
            elif event.event_type == "hitl_resolved":
                review_id = event.payload["review_id"]
                hitl_by_review.setdefault(review_id, []).append(event)
            elif event.event_type == "rotation_event":
                key = event.payload["key_name"]
                rotation_by_key.setdefault(key, []).append(event)

        chains: List[EvidenceChain] = []

        for review_id, chain_events in hitl_by_review.items():
            ordered = sorted(chain_events, key=lambda e: e.sequence_number)
            resolved = any(e.event_type == "hitl_resolved" for e in ordered)
            chains.append(
                EvidenceChain(
                    chain_id=_chain_id("hitl", review_id),
                    chain_type="hitl_lifecycle",
                    event_ids=[e.event_id for e in ordered],
                    started_at=ordered[0].timestamp,
                    completed_at=ordered[-1].timestamp if resolved else None,
                    status="closed" if resolved else "open",
                )
            )

        for key_name, chain_events in rotation_by_key.items():
            ordered = sorted(chain_events, key=lambda e: e.sequence_number)
            chains.append(
                EvidenceChain(
                    chain_id=_chain_id("rotation", key_name),
                    chain_type="rotation_lifecycle",
                    event_ids=[e.event_id for e in ordered],
                    started_at=ordered[0].timestamp,
                    completed_at=ordered[-1].timestamp,
                    status="closed",
                )
            )

        return chains


def _chain_id(prefix: str, key: str) -> str:
    import hashlib

    digest = hashlib.sha256(f"{prefix}:{key}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


_STORE: Any = None


@dataclass
class ControlMapping:
    """
    Links one EvidenceEvent to N compliance controls it satisfies.
    """

    mapping_id: str
    event_id: str
    control_id: str
    framework_id: str
    satisfied: bool
    mapped_at: str

    @classmethod
    def attach_store(cls, store: Any) -> None:
        global _STORE
        _STORE = store

    @classmethod
    def for_event(cls, event_id: str) -> List["ControlMapping"]:
        if _STORE is None:
            return []
        return _STORE.list_mappings_for_event(event_id)

    @classmethod
    def events_for_control(
        cls,
        control_id: str,
        agent_id: str,
        since: str,
        until: str,
        *,
        store: Any = None,
    ) -> List[EvidenceEvent]:
        active_store = store or _STORE
        if active_store is None:
            return []
        return active_store.events_for_control(control_id, agent_id, since, until)


@dataclass
class RetentionPolicy:
    """
    Computed retention requirement for an event — longest control wins.
    """

    event_id: str
    retention_days: int
    eligible_for_deletion_at: str
    deletion_hold: bool = False
    erasure_requested: bool = False

    @classmethod
    def compute_for_event(cls, event_id: str, *, store: Any = None) -> "RetentionPolicy":
        from iris_core.evidence.retention import compute_retention_policy

        active_store = store or _STORE
        if active_store is None:
            from iris_core.evidence.retention import DEFAULT_RETENTION_DAYS

            now = datetime.utcnow().isoformat()
            return cls(
                event_id=event_id,
                retention_days=DEFAULT_RETENTION_DAYS,
                eligible_for_deletion_at=now,
            )

        event = active_store.get_event(event_id)
        mappings = active_store.list_mappings_for_event(event_id)
        hold = active_store.get_deletion_hold(event_id)
        erasure = active_store.is_erasure_requested(event_id)
        return compute_retention_policy(
            event_id,
            event.timestamp,
            mappings,
            deletion_hold=hold,
            erasure_requested=erasure,
        )
