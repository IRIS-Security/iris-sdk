"""Evidence lifecycle: capture, index, query, retention, disposition."""

from __future__ import annotations

import os
import uuid
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from iris_core.evidence.index import EvidenceIndexer, framework_coverage
from iris_core.evidence.models import EvidenceChain, EvidenceEvent, RetentionPolicy
from iris_core.evidence.retention import compute_retention_policy
from iris_core.evidence.schemas import validate_payload
from iris_core.evidence.signing import (
    compute_event_content_hash,
    compute_payload_hash,
    sign_event_content,
)
from iris_core.evidence.store import EvidenceStore

UNSCOPED_QUERY_LIMIT = 500


class RateLimitExceeded(Exception):
    """Raised when an agent exceeds vault write rate limits."""


class UnscopedQueryError(ValueError):
    """Raised when a query lacks required scoping."""


class EvidenceLifecycle:
    """Orchestrates the five lifecycle stages."""

    def __init__(
        self,
        store: EvidenceStore,
        *,
        rate_limit_per_minute: int = 120,
    ):
        self.store = store
        self.indexer = EvidenceIndexer(store)
        self.rate_limit_per_minute = rate_limit_per_minute
        self._write_timestamps: deque[float] = deque()
        self._index_failures: List[str] = []

    def _check_rate_limit(self) -> None:
        now = datetime.utcnow().timestamp()
        window_start = now - 60
        while self._write_timestamps and self._write_timestamps[0] < window_start:
            self._write_timestamps.popleft()
        if len(self._write_timestamps) >= self.rate_limit_per_minute:
            raise RateLimitExceeded(
                f"Rate limit exceeded: {self.rate_limit_per_minute}/minute"
            )
        self._write_timestamps.append(now)

    def capture(
        self,
        *,
        event_type: str,
        agent_name: str,
        environment: Optional[str] = None,
        payload: dict,
    ) -> EvidenceEvent:
        """STAGE 1 — CAPTURE: append-only write with signing and chaining."""
        try:
            self._check_rate_limit()
        except RateLimitExceeded as exc:
            self.store.append_event(
                event_type="vault_rate_limited",
                agent_name=agent_name,
                environment=environment or _resolve_environment(),
                payload={
                    "limit_per_minute": self.rate_limit_per_minute,
                    "attempted_event_type": event_type,
                    "client_id": self.store.agent_id,
                },
            )
            raise exc

        event = self.store.append_event(
            event_type=event_type,
            agent_name=agent_name,
            environment=environment or _resolve_environment(),
            payload=payload,
        )
        self._index_async(event)
        return event

    def _index_async(self, event: EvidenceEvent) -> None:
        """STAGE 2 — INDEX: best-effort, non-blocking."""
        try:
            self.indexer.index_event(event)
        except Exception:
            self._index_failures.append(event.event_id)

    def retry_failed_indexing(self) -> int:
        """Recover indexing failures without losing captured events."""
        recovered = 0
        pending = list(self._index_failures)
        self._index_failures.clear()
        for event_id in pending:
            event = self.store.get_event(event_id)
            if self.store.list_mappings_for_event(event_id):
                continue
            self.indexer.index_event(event)
            recovered += 1
        return recovered

    def query_events(
        self,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[EvidenceEvent]:
        """STAGE 3 — QUERY: read-only, scoped."""
        if not since and not until and not event_type:
            total = len(self.store.list_events())
            if total > UNSCOPED_QUERY_LIMIT:
                raise UnscopedQueryError(
                    f"Unscoped query rejected: {total} events exceed "
                    f"threshold of {UNSCOPED_QUERY_LIMIT}. "
                    "Provide since/until/event_type."
                )

        events = self.store.list_events()
        if since:
            since_norm = since if "T" in since else f"{since}T00:00:00"
            events = [e for e in events if e.timestamp >= since_norm]
        if until:
            until_norm = until if "T" in until else f"{until}T23:59:59"
            events = [e for e in events if e.timestamp <= until_norm]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[offset : offset + limit]

    def query_chains(
        self,
        *,
        chain_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[EvidenceChain]:
        chains = self.indexer.rebuild_chains()
        if chain_type:
            chains = [c for c in chains if c.chain_type == chain_type]
        if status:
            chains = [c for c in chains if c.status == status]
        return chains

    def run_retention_check(self, *, now: Optional[datetime] = None) -> List[str]:
        """STAGE 4 — RETENTION CHECK: daily scheduled job."""
        reference = now or datetime.utcnow()
        marked: List[str] = []
        for event in self.store.list_events():
            if event.event_type == "event_expired":
                continue
            policy = RetentionPolicy.compute_for_event(event.event_id, store=self.store)
            if policy.deletion_hold:
                self.capture(
                    event_type="retention_extended",
                    agent_name=event.agent_name,
                    environment=event.environment,
                    payload={
                        "event_id": event.event_id,
                        "reason": "legal_hold",
                        "hold_until": policy.eligible_for_deletion_at,
                    },
                )
                continue
            if policy.erasure_requested:
                continue
            eligible = datetime.fromisoformat(
                policy.eligible_for_deletion_at.replace("Z", "")
            )
            if reference >= eligible:
                marked.append(event.event_id)
        return marked

    def dispose_expired_event(
        self,
        event_id: str,
        *,
        reason: str = "retention_period_elapsed",
    ) -> EvidenceEvent:
        """STAGE 5 — DISPOSITION (a): tombstone + payload scrub."""
        original = self.store.get_event(event_id)
        expired_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        tombstone_payload = validate_payload(
            "event_expired",
            {
                "original_event_id": event_id,
                "original_event_type": original.event_type,
                "expired_at": expired_at,
                "reason": reason,
            },
        )
        tombstone = self.capture(
            event_type="event_expired",
            agent_name=original.agent_name,
            environment=original.environment,
            payload=tombstone_payload,
        )
        self.store.scrub_event_payload(
            event_id,
            {
                "_scrubbed": True,
                "original_event_type": original.event_type,
                "timestamp": original.timestamp,
            },
        )
        return tombstone

    def dispose_erasure(self, event_id: str) -> EvidenceEvent:
        """STAGE 5 — DISPOSITION (b): GDPR erasure with mapping preservation."""
        return self.dispose_expired_event(event_id, reason="erasure_request")


def _resolve_environment() -> str:
    return os.environ.get("IRIS_ENV", "dev")
