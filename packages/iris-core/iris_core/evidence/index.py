"""Control mapping inference and chain indexing for Evidence Vault v2."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from iris_core.evidence.models import ControlMapping, EvidenceChain, EvidenceEvent
from iris_core.evidence.store import EvidenceStore

EVENT_CONTROL_MAP: Dict[str, List[Tuple[str, str]]] = {
    "cedar_decision": [],  # derived from payload.rule_id + payload.framework
    "hitl_requested": [("CO-004", "colorado-ai-act"), ("C007", "aiuc-1")],
    "hitl_resolved": [("CO-004", "colorado-ai-act"), ("C007", "aiuc-1")],
    "dlp_finding": [("HIPAA-006", "hipaa"), ("A006", "aiuc-1")],
    "drift_detected": [("CO-DEV-001", "colorado-ai-act")],
    "agent_registered": [("CO-001", "colorado-ai-act"), ("B006", "aiuc-1")],
    "policy_compiled": [("CO-003", "colorado-ai-act"), ("D003", "aiuc-1")],
    "rotation_event": [("FEDRAMP-001", "fedramp")],
    "org_policy_changed": [("CO-003", "colorado-ai-act")],
    "cicd_run": [("CO-002", "colorado-ai-act"), ("E015", "aiuc-1")],
}


def infer_control_mappings(event: EvidenceEvent) -> List[Tuple[str, str, bool]]:
    """Return (control_id, framework_id, satisfied) tuples for an event."""
    mappings: List[Tuple[str, str, bool]] = []

    if event.event_type == "cedar_decision":
        rule_id = event.payload.get("rule_id", "")
        framework = event.payload.get("framework", "colorado-ai-act")
        action = event.payload.get("action", "PERMIT")
        satisfied = action in {"PERMIT", "HITL"}
        if rule_id:
            mappings.append((rule_id, framework, satisfied))
        return mappings

    for control_id, framework_id in EVENT_CONTROL_MAP.get(event.event_type, []):
        mappings.append((control_id, framework_id, True))

    return mappings


class EvidenceIndexer:
    """Asynchronous index stage — never blocks capture."""

    def __init__(self, store: EvidenceStore):
        self.store = store
        self._fail_next = False

    def simulate_failure_on_next_index(self) -> None:
        self._fail_next = True

    def index_event(self, event: EvidenceEvent) -> List[ControlMapping]:
        if self._fail_next:
            self._fail_next = False
            raise RuntimeError("simulated indexing failure")

        created: List[ControlMapping] = []
        for control_id, framework_id, satisfied in infer_control_mappings(event):
            created.append(
                self.store.add_control_mapping(
                    event.event_id,
                    control_id,
                    framework_id,
                    satisfied=satisfied,
                )
            )
        return created

    def rebuild_chains(self) -> List[EvidenceChain]:
        return EvidenceChain.rebuild_from_events(self.store.list_events())


def framework_coverage(
    store: EvidenceStore,
    framework_id: str,
    control_ids: List[str],
    agent_id: str,
) -> dict:
    """Aggregate FULL/PARTIAL/NONE coverage for iris certify."""
    since = "1970-01-01"
    until = datetime.utcnow().strftime("%Y-%m-%dT23:59:59")
    breakdown = {"FULL": 0, "PARTIAL": 0, "NONE": 0, "controls": {}}

    for control_id in control_ids:
        events = store.events_for_control(control_id, agent_id, since, until)
        if len(events) >= 3:
            status = "FULL"
        elif events:
            status = "PARTIAL"
        else:
            status = "NONE"
        breakdown[status] += 1
        breakdown["controls"][control_id] = {
            "status": status,
            "event_count": len(events),
        }

    return breakdown
