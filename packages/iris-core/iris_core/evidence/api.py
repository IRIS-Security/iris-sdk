"""Evidence Vault v2 REST-style API — one write path, many read paths."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from iris_core.evidence.index import framework_coverage
from iris_core.evidence.lifecycle import (
    EvidenceLifecycle,
    RateLimitExceeded,
    UnscopedQueryError,
)
from iris_core.evidence.models import ControlMapping, EvidenceEvent
from iris_core.evidence.schemas import validate_payload
from iris_core.evidence.signing import hash_result_set, sign_query_result, verify_hash_chain
from iris_core.evidence.store import EvidenceStore

ALLOWED_WRITE = {"POST /v1/events"}
ALLOWED_READ = {
    "GET /v1/agents/:agent_id/events",
    "GET /v1/agents/:agent_id/chains",
    "GET /v1/controls/:control_id/evidence",
    "GET /v1/frameworks/:framework_id/coverage",
    "GET /v1/agents/:agent_id/integrity",
    "GET /v1/agents/:agent_id/export",
}
ALLOWED_ADMIN = {
    "POST /v1/erasure-requests",
    "POST /v1/legal-holds",
    "DELETE /v1/legal-holds/:hold_id",
}

FORBIDDEN_ROUTES = {
    "DELETE /v1/events",
    "PATCH /v1/events",
    "PUT /v1/events",
}


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class APIResponse:
    status: int
    body: dict


class EvidenceVaultAPI:
    """Local API facade — callable from CLI, tests, and HTTP adapters."""

    def __init__(
        self,
        agent_id: str,
        vault_dir=None,
        signing_key: Optional[bytes] = None,
    ):
        self.agent_id = agent_id
        self.store = EvidenceStore(agent_id, vault_dir=vault_dir, signing_key=signing_key)
        self.lifecycle = EvidenceLifecycle(self.store)

    def dispatch(self, method: str, path: str, body: Optional[dict] = None, query: Optional[dict] = None) -> APIResponse:
        query = dict(query or {})
        _inject_path_params(method, path, query)
        route = f"{method.upper()} {path.split('?')[0]}"
        if route in FORBIDDEN_ROUTES:
            raise APIError(405, f"Method not allowed: {route}")

        handlers: Dict[str, Callable[..., APIResponse]] = {
            "POST /v1/events": self.post_event,
            "GET /v1/agents/:agent_id/events": self.get_events,
            "GET /v1/agents/:agent_id/chains": self.get_chains,
            "GET /v1/controls/:control_id/evidence": self.get_control_evidence,
            "GET /v1/frameworks/:framework_id/coverage": self.get_framework_coverage,
            "GET /v1/agents/:agent_id/integrity": self.get_integrity,
            "GET /v1/agents/:agent_id/export": self.get_export,
            "POST /v1/erasure-requests": self.post_erasure_request,
            "POST /v1/legal-holds": self.post_legal_hold,
            "DELETE /v1/legal-holds/:hold_id": self.delete_legal_hold,
        }

        normalized = _normalize_route(method, path)
        handler = handlers.get(normalized)
        if handler is None:
            raise APIError(404, f"Unknown route: {method} {path}")

        return handler(body=body or {}, query=query or {})

    def post_event(self, *, body: dict, query: dict) -> APIResponse:
        event_type = body.get("event_type")
        if not event_type:
            raise APIError(400, "event_type is required")

        payload = body.get("payload") or {}
        try:
            validate_payload(event_type, payload)
        except Exception as exc:
            raise APIError(400, str(exc)) from exc

        agent_name = body.get("agent_name") or self.agent_id
        environment = body.get("environment")

        try:
            event = self.lifecycle.capture(
                event_type=event_type,
                agent_name=agent_name,
                environment=environment,
                payload=payload,
            )
        except RateLimitExceeded as exc:
            raise APIError(429, str(exc)) from exc

        return APIResponse(
            status=201,
            body={
                "event_id": event.event_id,
                "sequence_number": event.sequence_number,
                "signature": event.signature,
                "timestamp": event.timestamp,
            },
        )

    def get_events(self, *, body: dict, query: dict) -> APIResponse:
        agent_id = _agent_from_path_query(query, self.agent_id)
        if agent_id != self.agent_id:
            raise APIError(404, f"Agent not found: {agent_id}")

        try:
            events = self.lifecycle.query_events(
                since=query.get("since"),
                until=query.get("until"),
                event_type=query.get("event_type"),
                limit=int(query.get("limit", 100)),
                offset=int(query.get("offset", 0)),
            )
        except UnscopedQueryError as exc:
            raise APIError(400, str(exc)) from exc

        return self._wrap_query(events, query, [e.to_storage_dict() for e in events])

    def get_chains(self, *, body: dict, query: dict) -> APIResponse:
        chains = self.lifecycle.query_chains(
            chain_type=query.get("chain_type"),
            status=query.get("status"),
        )
        rows = [
            {
                "chain_id": c.chain_id,
                "chain_type": c.chain_type,
                "event_ids": c.event_ids,
                "started_at": c.started_at,
                "completed_at": c.completed_at,
                "status": c.status,
            }
            for c in chains
        ]
        return self._wrap_query(chains, query, rows)

    def get_control_evidence(self, *, body: dict, query: dict) -> APIResponse:
        control_id = query.get("control_id") or body.get("control_id")
        agent_id = query.get("agent_id") or self.agent_id
        since = query.get("since") or "1970-01-01"
        until = query.get("until") or "9999-12-31"

        events = ControlMapping.events_for_control(
            control_id, agent_id, since, until, store=self.store
        )
        chains = self.lifecycle.query_chains()
        chain_context = {
            c.chain_id: c
            for c in chains
            if any(eid in c.event_ids for eid in [e.event_id for e in events])
        }
        rows = [
            {
                **event.to_storage_dict(),
                "chain_context": [
                    {
                        "chain_id": chain.chain_id,
                        "chain_type": chain.chain_type,
                        "status": chain.status,
                    }
                    for chain in chain_context.values()
                    if event.event_id in chain.event_ids
                ],
            }
            for event in events
        ]
        return self._wrap_query(events, query, rows)

    def get_framework_coverage(self, *, body: dict, query: dict) -> APIResponse:
        framework_id = query.get("framework_id") or body.get("framework_id")
        agent_id = query.get("agent_id") or self.agent_id
        control_ids = _framework_controls(framework_id)
        coverage = framework_coverage(self.store, framework_id, control_ids, agent_id)
        return self._wrap_query([coverage], query, [coverage])

    def get_integrity(self, *, body: dict, query: dict) -> APIResponse:
        events = [e.to_storage_dict() for e in self.store.list_events()]
        valid, broken, checked = verify_hash_chain(events, self.store.signing_key)
        payload = {"valid": valid, "events_checked": checked}
        if not valid:
            payload["first_broken_link"] = broken
        return APIResponse(status=200, body=payload)

    def get_export(self, *, body: dict, query: dict) -> APIResponse:
        export_format = query.get("format", "json")
        since = query.get("since") or "1970-01-01"
        until = query.get("until") or "9999-12-31"
        events = self.lifecycle.query_events(since=since, until=until, limit=10_000)
        mappings = [
            {
                "mapping_id": m.mapping_id,
                "event_id": m.event_id,
                "control_id": m.control_id,
                "framework_id": m.framework_id,
                "satisfied": m.satisfied,
            }
            for event in events
            for m in self.store.list_mappings_for_event(event.event_id)
        ]
        export_body = {
            "format": export_format,
            "agent_id": self.agent_id,
            "events": [e.to_storage_dict() for e in events],
            "control_mappings": mappings,
        }
        if export_format == "aiuc1":
            export_body["aiuc1_controls"] = _aiuc1_from_mappings(mappings, events)
        return self._wrap_query(events, query, [export_body])

    def post_erasure_request(self, *, body: dict, query: dict) -> APIResponse:
        user_id_hash = body.get("user_id_hash")
        reason = body.get("reason", "gdpr_art_17")
        if not user_id_hash:
            raise APIError(400, "user_id_hash is required")
        matched = self.store.request_erasure(user_id_hash, reason)
        for event_id in matched:
            self.lifecycle.dispose_erasure(event_id)
        return APIResponse(
            status=202,
            body={"events_marked": len(matched), "event_ids": matched},
        )

    def post_legal_hold(self, *, body: dict, query: dict) -> APIResponse:
        event_ids = body.get("event_id_range") or body.get("event_ids") or []
        hold_id = self.store.add_legal_hold(
            event_ids,
            reason=body.get("reason", ""),
            requested_by=body.get("requested_by", "admin"),
        )
        return APIResponse(status=201, body={"hold_id": hold_id})

    def delete_legal_hold(self, *, body: dict, query: dict) -> APIResponse:
        hold_id = query.get("hold_id") or body.get("hold_id")
        if not hold_id:
            raise APIError(400, "hold_id is required")
        removed = self.store.remove_legal_hold(hold_id)
        if not removed:
            raise APIError(404, f"Hold not found: {hold_id}")
        return APIResponse(status=200, body={"removed": True, "hold_id": hold_id})

    def _wrap_query(self, events_or_rows, query: dict, rows: List[dict]) -> APIResponse:
        events = self.store.list_events()
        event_dicts = [e.to_storage_dict() for e in events]
        chain_valid, _, _ = verify_hash_chain(event_dicts, self.store.signing_key)
        result_hash = hash_result_set(rows)
        query_signature = sign_query_result(query, result_hash, self.store.signing_key)
        return APIResponse(
            status=200,
            body={
                "data": rows,
                "integrity": {
                    "hash_chain_valid": chain_valid,
                    "events_returned": len(rows),
                    "query_signature": query_signature,
                },
            },
        )


def _inject_path_params(method: str, path: str, query: dict) -> None:
    parts = [p for p in path.split("?")[0].strip("/").split("/") if p]
    if len(parts) >= 3 and parts[0] == "v1":
        if parts[1] == "agents" and len(parts) >= 3:
            query.setdefault("agent_id", parts[2])
        if parts[1] == "controls" and len(parts) >= 3:
            query.setdefault("control_id", parts[2])
        if parts[1] == "frameworks" and len(parts) >= 3:
            query.setdefault("framework_id", parts[2])
        if parts[1] == "legal-holds" and len(parts) >= 3 and method.upper() == "DELETE":
            query.setdefault("hold_id", parts[2])


def _normalize_route(method: str, path: str) -> str:
    path_only = path.split("?")[0]
    parts = [p for p in path_only.strip("/").split("/") if p]
    if len(parts) >= 3 and parts[0] == "v1":
        if parts[1] == "agents" and len(parts) >= 4:
            parts[2] = ":agent_id"
        if parts[1] == "controls" and len(parts) >= 3:
            parts[2] = ":control_id"
        if parts[1] == "frameworks" and len(parts) >= 3:
            parts[2] = ":framework_id"
        if parts[1] == "legal-holds" and len(parts) >= 3:
            parts[2] = ":hold_id"
    normalized = "/" + "/".join(parts)
    return f"{method.upper()} {normalized}"


def _agent_from_path_query(query: dict, default: str) -> str:
    return query.get("agent_id") or default


def _framework_controls(framework_id: str) -> List[str]:
    catalog = {
        "colorado-ai-act": ["CO-001", "CO-002", "CO-003", "CO-004", "CO-RR-001"],
        "aiuc-1": ["B006", "C007", "C008", "E015"],
        "hipaa": ["HIPAA-001", "HIPAA-006"],
        "nyc-ll144": ["LL144-005"],
    }
    return catalog.get(framework_id, [])


def _aiuc1_from_mappings(mappings: List[dict], events: List[EvidenceEvent]) -> dict:
    by_control: dict[str, list] = {}
    event_by_id = {e.event_id: e for e in events}
    for mapping in mappings:
        if mapping["framework_id"] != "aiuc-1":
            continue
        control = mapping["control_id"]
        event = event_by_id.get(mapping["event_id"])
        if not event:
            continue
        by_control.setdefault(control, []).append(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "timestamp": event.timestamp,
                "payload": event.payload,
            }
        )
    return by_control


def route_exists(method: str, path: str) -> bool:
    normalized = _normalize_route(method, path)
    allowed = ALLOWED_WRITE | ALLOWED_READ | ALLOWED_ADMIN
    return normalized in allowed


def forbidden_route_exists(method: str, path: str) -> bool:
    return f"{method.upper()} {path.split('?')[0]}" in FORBIDDEN_ROUTES
