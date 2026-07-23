"""Evidence Vault v2 facade — append-only system of record."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from iris_core.evidence.api import EvidenceVaultAPI
from iris_core.evidence.lifecycle import EvidenceLifecycle
from iris_core.evidence.models import EvidenceChain, EvidenceEvent, RetentionPolicy
from iris_core.evidence.store import EvidenceStore


class EvidenceVaultV2:
    """
    Immutable, queryable, signed evidence ledger.

    Single write path: append EvidenceEvent via capture().
    """

    def __init__(
        self,
        agent_id: str,
        vault_dir: Optional[Path] = None,
        signing_key: Optional[bytes] = None,
    ):
        self.agent_id = agent_id
        self.store = EvidenceStore(agent_id, vault_dir=vault_dir, signing_key=signing_key)
        self.lifecycle = EvidenceLifecycle(self.store)
        self.api = EvidenceVaultAPI(agent_id, vault_dir=vault_dir, signing_key=signing_key)

    def capture(
        self,
        event_type: str,
        payload: dict,
        *,
        agent_name: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> EvidenceEvent:
        return self.lifecycle.capture(
            event_type=event_type,
            agent_name=agent_name or self.agent_id,
            environment=environment,
            payload=payload,
        )

    def record_cicd(
        self,
        *,
        system: str,
        run_id: str,
        pipeline_url: str = "",
        triggered_by: str = "automated",
        outcome: str = "success",
    ) -> EvidenceEvent:
        return self.capture(
            event_type="cicd_run",
            payload={
                "system": system,
                "run_id": run_id,
                "pipeline_url": pipeline_url,
                "triggered_by": triggered_by,
                "outcome": outcome,
            },
        )

    def list_events(self, **kwargs) -> List[EvidenceEvent]:
        return self.lifecycle.query_events(**kwargs)

    def rebuild_chains(self) -> List[EvidenceChain]:
        return self.lifecycle.query_chains()

    def retention_policy(self, event_id: str) -> RetentionPolicy:
        return RetentionPolicy.compute_for_event(event_id, store=self.store)

    def check_integrity(self) -> dict:
        response = self.api.get_integrity(body={}, query={"agent_id": self.agent_id})
        return response.body
