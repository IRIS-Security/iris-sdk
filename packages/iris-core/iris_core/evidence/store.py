"""Append-only Evidence Vault storage."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from iris_core.evidence.models import ControlMapping, EvidenceEvent
from iris_core.evidence.retention import retention_days_for_control
from iris_core.evidence.schemas import validate_payload
from iris_core.evidence.signing import (
    GENESIS_HASH,
    compute_event_content_hash,
    compute_payload_hash,
    sign_event_content,
)


class EvidenceStore:
    """Local append-only store — one write path: append_event."""

    EVENTS_FILE = "evidence_events.jsonl"
    MAPPINGS_FILE = "control_mappings.jsonl"
    HOLDS_FILE = "legal_holds.json"
    ERASURES_FILE = "erasure_requests.json"

    def __init__(
        self,
        agent_id: str,
        vault_dir: Optional[Path] = None,
        signing_key: Optional[bytes] = None,
    ):
        self.agent_id = agent_id
        self._dir = (vault_dir or Path.home() / ".iris" / "evidence") / agent_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._events_path = self._dir / self.EVENTS_FILE
        self._mappings_path = self._dir / self.MAPPINGS_FILE
        self._holds_path = self._dir / self.HOLDS_FILE
        self._erasures_path = self._dir / self.ERASURES_FILE
        self._signing_key = signing_key or self._default_signing_key(agent_id)
        ControlMapping.attach_store(self)

    @staticmethod
    def _default_signing_key(agent_id: str) -> bytes:
        material = f"iris-evidence-vault:{agent_id}:{os.environ.get('IRIS_VAULT_SIGNING_KEY', 'local-dev')}"
        import hashlib

        return hashlib.sha256(material.encode("utf-8")).digest()

    @property
    def signing_key(self) -> bytes:
        return self._signing_key

    def _read_jsonl(self, path: Path) -> List[dict]:
        if not path.exists():
            return []
        rows: List[dict] = []
        with open(path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def _append_jsonl(self, path: Path, row: dict) -> None:
        with open(path, "a") as handle:
            handle.write(json.dumps(row) + "\n")

    def list_events(self) -> List[EvidenceEvent]:
        return [
            EvidenceEvent.from_storage_dict(row)
            for row in self._read_jsonl(self._events_path)
        ]

    def iter_events(self) -> Iterator[EvidenceEvent]:
        for row in self._read_jsonl(self._events_path):
            yield EvidenceEvent.from_storage_dict(row)

    def get_event(self, event_id: str) -> EvidenceEvent:
        for event in self.iter_events():
            if event.event_id == event_id:
                return event
        raise KeyError(event_id)

    def next_sequence_number(self) -> int:
        events = self.list_events()
        if not events:
            return 1
        return max(e.sequence_number for e in events) + 1

    def last_event_hash(self) -> str:
        events = self.list_events()
        if not events:
            return GENESIS_HASH
        last = events[-1]
        return compute_event_content_hash(
            last.event_id,
            last.sequence_number,
            last.payload_hash,
            last.prev_event_hash,
        )

    def append_event(
        self,
        *,
        event_type: str,
        agent_name: str,
        environment: str,
        payload: dict,
        pii_redacted: bool = True,
    ) -> EvidenceEvent:
        """The ONLY authoritative write path for new facts."""
        validated = validate_payload(event_type, payload)
        sequence = self.next_sequence_number()
        prev_hash = self.last_event_hash()
        event_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        payload_hash = compute_payload_hash(validated)
        signature = sign_event_content(
            event_id, sequence, payload_hash, prev_hash, self._signing_key
        )
        event = EvidenceEvent(
            event_id=event_id,
            event_type=event_type,
            agent_id=self.agent_id,
            agent_name=agent_name,
            environment=environment,
            timestamp=timestamp,
            sequence_number=sequence,
            payload=validated,
            payload_hash=payload_hash,
            signature=signature,
            prev_event_hash=prev_hash,
            pii_redacted=pii_redacted,
        )
        self._append_jsonl(self._events_path, event.to_storage_dict())
        return event

    def append_signed_event(self, event: EvidenceEvent) -> EvidenceEvent:
        """Persist a fully constructed event (used for tombstones)."""
        self._append_jsonl(self._events_path, event.to_storage_dict())
        return event

    def scrub_event_payload(self, event_id: str, scrubbed_payload: dict) -> None:
        """
        Disposition path: replace payload while preserving chain metadata.
        Not a general update API — only used by lifecycle disposition.
        """
        rows = self._read_jsonl(self._events_path)
        updated: List[dict] = []
        for row in rows:
            if row.get("event_id") != event_id:
                updated.append(row)
                continue
            row = dict(row)
            row["payload"] = scrubbed_payload
            row["payload_hash"] = compute_payload_hash(scrubbed_payload)
            updated.append(row)
        with open(self._events_path, "w") as handle:
            for row in updated:
                handle.write(json.dumps(row) + "\n")

    def list_mappings_for_event(self, event_id: str) -> List[ControlMapping]:
        mappings: List[ControlMapping] = []
        for row in self._read_jsonl(self._mappings_path):
            if row.get("event_id") != event_id:
                continue
            mappings.append(
                ControlMapping(
                    mapping_id=row["mapping_id"],
                    event_id=row["event_id"],
                    control_id=row["control_id"],
                    framework_id=row["framework_id"],
                    satisfied=row["satisfied"],
                    mapped_at=row["mapped_at"],
                )
            )
        return mappings

    def add_control_mapping(
        self,
        event_id: str,
        control_id: str,
        framework_id: str,
        *,
        satisfied: bool = True,
    ) -> ControlMapping:
        mapping = ControlMapping(
            mapping_id=str(uuid.uuid4()),
            event_id=event_id,
            control_id=control_id,
            framework_id=framework_id,
            satisfied=satisfied,
            mapped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        )
        self._append_jsonl(
            self._mappings_path,
            {
                "mapping_id": mapping.mapping_id,
                "event_id": mapping.event_id,
                "control_id": mapping.control_id,
                "framework_id": mapping.framework_id,
                "satisfied": mapping.satisfied,
                "mapped_at": mapping.mapped_at,
            },
        )
        return mapping

    def events_for_control(
        self,
        control_id: str,
        agent_id: str,
        since: str,
        until: str,
    ) -> List[EvidenceEvent]:
        if agent_id != self.agent_id:
            return []
        event_ids = {
            row["event_id"]
            for row in self._read_jsonl(self._mappings_path)
            if row.get("control_id") == control_id and row.get("satisfied") is True
        }
        since_norm = since if "T" in since else f"{since}T00:00:00"
        until_norm = until if "T" in until else f"{until}T23:59:59"
        return [
            event
            for event in self.list_events()
            if event.event_id in event_ids
            and since_norm <= event.timestamp <= until_norm
        ]

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        with open(path) as handle:
            return json.load(handle)

    def _save_json(self, path: Path, data: dict) -> None:
        with open(path, "w") as handle:
            json.dump(data, handle, indent=2)

    def get_deletion_hold(self, event_id: str) -> bool:
        holds = self._load_json(self._holds_path).get("event_ids", [])
        return event_id in holds

    def is_erasure_requested(self, event_id: str) -> bool:
        return event_id in self._load_json(self._erasures_path).get("event_ids", [])

    def add_legal_hold(self, event_ids: List[str], reason: str, requested_by: str) -> str:
        data = self._load_json(self._holds_path)
        hold_id = str(uuid.uuid4())
        holds = data.setdefault("holds", [])
        holds.append(
            {
                "hold_id": hold_id,
                "event_ids": event_ids,
                "reason": reason,
                "requested_by": requested_by,
                "created_at": datetime.utcnow().isoformat(),
            }
        )
        all_ids = set(data.get("event_ids", []))
        all_ids.update(event_ids)
        data["event_ids"] = sorted(all_ids)
        self._save_json(self._holds_path, data)
        return hold_id

    def remove_legal_hold(self, hold_id: str) -> bool:
        data = self._load_json(self._holds_path)
        holds = data.get("holds", [])
        remaining = [h for h in holds if h.get("hold_id") != hold_id]
        if len(remaining) == len(holds):
            return False
        data["holds"] = remaining
        all_ids: set[str] = set()
        for hold in remaining:
            all_ids.update(hold.get("event_ids", []))
        data["event_ids"] = sorted(all_ids)
        self._save_json(self._holds_path, data)
        return True

    def request_erasure(self, user_id_hash: str, reason: str) -> List[str]:
        data = self._load_json(self._erasures_path)
        matched: List[str] = []
        for event in self.list_events():
            payload_blob = json.dumps(event.payload)
            if user_id_hash in payload_blob:
                matched.append(event.event_id)
        all_ids = set(data.get("event_ids", []))
        all_ids.update(matched)
        data.setdefault("requests", []).append(
            {
                "user_id_hash": user_id_hash,
                "reason": reason,
                "event_ids": matched,
                "requested_at": datetime.utcnow().isoformat(),
            }
        )
        data["event_ids"] = sorted(all_ids)
        self._save_json(self._erasures_path, data)
        return matched

    def retention_days_for_mapped_controls(self, event_id: str) -> int:
        mappings = self.list_mappings_for_event(event_id)
        if not mappings:
            from iris_core.evidence.retention import DEFAULT_RETENTION_DAYS

            return DEFAULT_RETENTION_DAYS
        return max(
            retention_days_for_control(m.control_id, m.framework_id) for m in mappings
        )
