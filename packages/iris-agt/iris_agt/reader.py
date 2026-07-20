"""Read Microsoft AGT audit-trail exports and derive workload profile metadata.

AGT (agent-governance-toolkit) runs in-process alongside the agents it
governs — there is no remote query API to call. The integration point is
whatever AGT already writes to disk: a FileAuditSink JSON-Lines export
(one AuditEntry-shaped object per line) or a CloudEvents v1.0 export. This
reader is file-based only; there is no "live" network mode.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from iris_agt._profile import build_profile_from_agt_entries

# Fields that must never be read — privacy guarantee for tool-call arguments
# and any other free-form payload content. AGT's `data` field on an
# AuditEntry is where prompt/tool-argument content would live.
_FORBIDDEN_CONTENT_FIELDS = frozenset({"data"})

_SAFE_ENTRY_FIELDS = frozenset(
    {
        "entry_id",
        "timestamp",
        "event_type",
        "agent_did",
        "action",
        "resource",
        "target_did",
        "outcome",
        "policy_decision",
        "matched_rule",
        "previous_hash",
        "entry_hash",
        "trace_id",
        "session_id",
    }
)


def _safe_dict(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        key: raw[key]
        for key in raw
        if key in _SAFE_ENTRY_FIELDS and key not in _FORBIDDEN_CONTENT_FIELDS
    }


def _normalize_entry(raw: Any) -> dict[str, Any]:
    return _safe_dict(raw)


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


def _parse_cloudevents(payload: Any) -> list[dict[str, Any]]:
    """Unwrap a CloudEvents v1.0 export (list of envelopes, or {"entries": [...]})."""
    if isinstance(payload, dict) and "entries" in payload:
        envelopes = payload["entries"]
    elif isinstance(payload, list):
        envelopes = payload
    else:
        raise ValueError("Unrecognized AGT export shape: expected a list or {'entries': [...]}")

    entries: list[dict[str, Any]] = []
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        # CloudEvents wraps the AuditEntry under "data"; unwrap one level here
        # (this is envelope structure, not audit-entry content) but still run
        # the unwrapped object through the same field allowlist.
        inner = envelope.get("data") if "type" in envelope and "source" in envelope else envelope
        entries.append(inner if isinstance(inner, dict) else envelope)
    return entries


def parse_agt_audit_trail(path: str | Path) -> list[dict[str, Any]]:
    """Parse an AGT audit-trail export file into normalized, privacy-safe entries.

    Accepts either JSON-Lines (AGT's FileAuditSink format — one AuditEntry
    object per line) or a single JSON document (a CloudEvents export, or a
    plain list/`{"entries": [...]}` export from `audit.export()`).
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"AGT audit trail not found: {file_path}")

    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    raw_entries: list[dict[str, Any]]
    if file_path.suffix == ".jsonl":
        raw_entries = _parse_jsonl(text)
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            # Not a single JSON document — fall back to JSON-Lines.
            raw_entries = _parse_jsonl(text)
        else:
            if isinstance(payload, list) and payload and "type" in payload[0] and "source" in payload[0]:
                raw_entries = _parse_cloudevents(payload)
            elif isinstance(payload, dict) and "entries" in payload:
                raw_entries = list(payload["entries"])
            elif isinstance(payload, list):
                raw_entries = payload
            else:
                raise ValueError(f"Unrecognized AGT export shape in {file_path}")

    return [_normalize_entry(entry) for entry in raw_entries]


def verify_chain_continuity(entries: list[dict[str, Any]]) -> tuple[bool, int | None]:
    """Check that each entry's previous_hash matches the prior entry's entry_hash.

    This is a structural continuity check over the exported subset, not an
    independent cryptographic re-derivation of AGT's SHA-256 hashes — we
    don't have AGT's exact hash-input serialization to recompute them
    ourselves. It still detects reordering or deletion within what was
    exported. Entries missing hash fields entirely (e.g. a CloudEvents
    export that didn't carry them) are skipped rather than treated as a
    break.
    """
    previous_hash: str | None = None
    for index, entry in enumerate(entries):
        entry_hash = entry.get("entry_hash")
        prev = entry.get("previous_hash")
        if entry_hash is None and prev is None:
            continue
        if previous_hash is not None and prev is not None and prev != previous_hash:
            return False, index
        previous_hash = entry_hash
    return True, None


def profile_from_agt(path: str | Path, *, verify_chain: bool = True) -> dict[str, Any]:
    """Derive a WorkloadProfile scan payload from an AGT audit-trail export.

    Set `verify_chain=False` to skip the continuity check (e.g. for a
    partial/filtered export where breaks are expected).
    """
    entries = parse_agt_audit_trail(path)
    if verify_chain:
        intact, broken_at = verify_chain_continuity(entries)
        if not intact:
            raise ValueError(
                f"AGT audit chain continuity broken at entry index {broken_at} "
                "(previous_hash does not match prior entry's entry_hash). "
                "Pass verify_chain=False to skip this check."
            )
    return build_profile_from_agt_entries(entries)
