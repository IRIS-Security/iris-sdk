"""Hash chain and HMAC signing for EvidenceEvent integrity."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Iterable, List, Mapping, Optional, Tuple

GENESIS_HASH = "0" * 64


def canonicalize_payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonicalize_payload(payload).encode("utf-8")).hexdigest()


def compute_event_content_hash(
    event_id: str,
    sequence_number: int,
    payload_hash: str,
    prev_event_hash: str,
) -> str:
    material = f"{event_id}:{sequence_number}:{payload_hash}:{prev_event_hash}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def sign_event_content(
    event_id: str,
    sequence_number: int,
    payload_hash: str,
    prev_event_hash: str,
    signing_key: bytes,
) -> str:
    content_hash = compute_event_content_hash(
        event_id, sequence_number, payload_hash, prev_event_hash
    )
    return hmac.new(signing_key, content_hash.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_event_signature(
    event_id: str,
    sequence_number: int,
    payload_hash: str,
    prev_event_hash: str,
    signature: str,
    signing_key: bytes,
) -> bool:
    expected = sign_event_content(
        event_id, sequence_number, payload_hash, prev_event_hash, signing_key
    )
    return hmac.compare_digest(expected, signature)


def verify_hash_chain(
    events: Iterable[Mapping[str, Any]],
    signing_key: bytes,
) -> Tuple[bool, Optional[str], int]:
    """
    Walk events in sequence order.

    Returns (valid, first_broken_link_event_id, events_checked).
    """
    prev_hash = GENESIS_HASH
    checked = 0
    last_sequence = 0

    for event in events:
        checked += 1
        event_id = event["event_id"]
        sequence = int(event["sequence_number"])
        payload = event.get("payload") or {}
        stored_payload_hash = event.get("payload_hash") or ""
        payload_hash = compute_payload_hash(payload)
        if stored_payload_hash and stored_payload_hash != payload_hash:
            return False, event_id, checked

        if sequence != last_sequence + 1:
            return False, event_id, checked

        if event.get("prev_event_hash") != prev_hash:
            return False, event_id, checked

        signature = event.get("signature", "")
        if not verify_event_signature(
            event_id,
            sequence,
            payload_hash,
            prev_hash,
            signature,
            signing_key,
        ):
            return False, event_id, checked

        prev_hash = compute_event_content_hash(
            event_id, sequence, payload_hash, prev_hash
        )
        last_sequence = sequence

    return True, None, checked


def sign_query_result(query_params: Mapping[str, Any], result_hash: str, signing_key: bytes) -> str:
    material = json.dumps(
        {"params": dict(sorted(query_params.items())), "result_hash": result_hash},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hmac.new(signing_key, material.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_result_set(rows: List[Mapping[str, Any]]) -> str:
    material = canonicalize_payload({"rows": rows})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
