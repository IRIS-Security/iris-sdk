"""
EvidenceVault: local file-based audit trail for all agent actions.

Pre-funding: writes to ~/.iris/evidence/<agent_id>/ as JSONL files.
Post-funding: syncs to the hosted IRIS control plane.

Every policy evaluation, violation, and HITL decision is recorded here.
This is what satisfies the Colorado AI Act impact assessment requirement
and provides the audit trail for SOC2 compliance.

Free tier retains events.jsonl for 30 days; Pro/Enterprise has unlimited retention.
assessments.jsonl is never pruned.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import json
import uuid

from iris_core.drift.notifier import BreachNotification
from iris_core.entitlements import Entitlements, Feature
from iris_core.models.passport import Environment


@dataclass
class VaultSummary:
    agent_id: str
    total_evaluations: int
    total_violations: int
    violations_by_severity: Dict[str, int]
    violations_by_rule: Dict[str, int]
    most_violated_rule: Optional[str]
    compliance_pass_rate: float
    last_assessment_date: Optional[str]
    last_reviewed_at: Optional[str]
    days_until_annual_review: Optional[int]
    environments_active: List[str]
    cross_region_blocks: int
    hitl_gates_triggered: int
    retention_days_remaining: int
    upgrade_available: bool


class EvidenceVault:
    FREE_RETENTION_DAYS = 30
    RETENTION_WARNING_DAYS = 25

    def __init__(self, agent_id: str, vault_dir: Optional[Path] = None):
        self._agent_id = agent_id
        self._dir = (vault_dir or Path.home() / ".iris" / "evidence") / agent_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._dir / "events.jsonl"
        self.prune_old_events()

    def record(self, context, result, passport=None, *, drift_score=None, drift_flagged=None, aarm_r7=None) -> str:
        event_id = str(uuid.uuid4())
        entry = {
            "event_id": event_id,
            "timestamp": datetime.utcnow().isoformat(),
            "agent_id": self._agent_id,
            "action": context.action,
            "resource": context.resource,
            "environment": context.environment.value,
            "decision": result.decision,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity.value,
                    "message": v.message,
                    "compliance_refs": v.compliance_refs,
                }
                for v in result.violations
            ],
        }
        if drift_score is not None:
            entry["drift_score"] = drift_score
        elif getattr(result, "drift_score", None) is not None:
            entry["drift_score"] = result.drift_score
        if drift_flagged is not None:
            entry["drift_flagged"] = drift_flagged
        elif getattr(result, "drift_flagged", False):
            entry["drift_flagged"] = result.drift_flagged
        if aarm_r7 or getattr(result, "aarm_r7", False):
            entry["aarm_r7"] = True

        if getattr(context, "is_delegated", False) and getattr(context, "user_context", None):
            user_ctx = context.user_context
            agent_name = passport.name if passport else self._agent_id
            entry = {
                "event_type": "delegated_call",
                "agent_name": agent_name,
                "acting_for_user": user_ctx.user_id,
                "user_email": user_ctx.user_email,
                "delegated_scopes": user_ctx.delegated_scopes,
                "consent_logged": user_ctx.consent_logged,
                "idp_provider": user_ctx.idp_provider,
                "session_id": user_ctx.session_id,
                "tool": context.resource if context.resource_type == "tool" else context.resource,
                "action": context.action,
                "decision": result.decision,
                "timestamp": entry["timestamp"],
                "event_id": event_id,
                "agent_id": self._agent_id,
                "environment": context.environment.value,
                "violations": entry["violations"],
            }

        with open(self._log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return event_id

    def record_drift(self, drift_event) -> str:
        """Record an intent drift event (AARM R7)."""
        from iris_core.drift.detector import IntentDriftEvent

        if not isinstance(drift_event, IntentDriftEvent):
            raise TypeError("drift_event must be an IntentDriftEvent")
        return self.record_raw(
            {
                "event_type": "intent_drift",
                "session_id": drift_event.session_id,
                "original_intent": drift_event.original_intent,
                "current_action": drift_event.current_action,
                "semantic_distance": drift_event.semantic_distance,
                "drift_threshold": drift_event.drift_threshold,
                "drift_flagged": drift_event.flagged,
                "drift_score": drift_event.semantic_distance,
                "aarm_r7": True,
                "timestamp": drift_event.timestamp,
            }
        )

    def record_cost_governance(
        self,
        *,
        within_budget: bool,
        decision: str,
        estimated_cost_usd: Optional[float] = None,
        cumulative_cost_usd: Optional[float] = None,
        overage_usd: float = 0.0,
        reason: str = "",
    ) -> str:
        """Record a governed-budget check — written on every call once a
        budget is configured, not just on overage, so "operated within its
        governed budget" is provable over time (not only a log of breaches)."""
        return self.record_raw(
            {
                "event_type": "cost_governance_check",
                "within_budget": within_budget,
                "decision": decision,
                "estimated_cost_usd": estimated_cost_usd,
                "cumulative_cost_usd": cumulative_cost_usd,
                "overage_usd": overage_usd,
                "reason": reason,
            }
        )

    def record_trust_state(
        self,
        *,
        trust_state: str,
        reason: str,
        violation_count: int,
        hitl_denial_count: int,
    ) -> str:
        """Record a trust-state check — written on every call once trust
        tracking is configured, not just on a downgrade, so the agent's
        trust posture is provable over time (not only a log of downgrades)."""
        return self.record_raw(
            {
                "event_type": "trust_state_check",
                "trust_state": trust_state,
                "reason": reason,
                "violation_count": violation_count,
                "hitl_denial_count": hitl_denial_count,
            }
        )

    def record_dlp_scan(
        self,
        event_type: str,
        result,
        environment: Environment,
        *,
        direction: str,
        redacted: bool = False,
    ) -> str:
        """
        Record a DLP scan event separately from policy violations.

        Never logs the actual sensitive value — only pattern metadata.
        """
        entry = {
            "event_type": event_type,
            "environment": environment.value,
            "direction": direction,
            "pattern_ids": [f.pattern_id for f in result.findings],
            "severities": [f.severity.value for f in result.findings],
            "findings": [
                {
                    "pattern_id": f.pattern_id,
                    "rule_id": f.rule_id,
                    "severity": f.severity.value,
                    "match_start": f.match_start,
                    "match_end": f.match_end,
                    "compliance_refs": f.compliance_refs,
                }
                for f in result.findings
            ],
            "redacted": redacted,
            "scan_duration_ms": result.scan_duration_ms,
            "has_critical": result.has_critical,
            "has_high": result.has_high,
        }
        return self.record_raw(entry)

    def record_raw(self, entry: dict) -> str:
        """Record a pre-built audit entry (e.g. SCM scan results)."""
        event_id = str(uuid.uuid4())
        payload = {
            "event_id": event_id,
            "timestamp": datetime.utcnow().isoformat(),
            "agent_id": self._agent_id,
            **entry,
        }
        with open(self._log_file, "a") as f:
            f.write(json.dumps(payload) + "\n")
        return event_id

    def record_hitl_requested(self, review) -> str:
        from iris_core.hitl.models import HITLReview

        if not isinstance(review, HITLReview):
            review = HITLReview.from_dict(review)
        return self.record_raw(
            {
                "event_type": "hitl_requested",
                "review_id": review.review_id,
                "agent_name": review.agent_name,
                "tool": review.tool_name,
                "risk_level": review.risk_level,
                "triggered_by": review.triggered_by_rule,
                "expires_at": review.expires_at,
                "timeout_policy": review.timeout_policy,
                "notifications_sent": review.notifications_sent,
                "review_type": review.review_type,
            }
        )

    def record_hitl_resolved(self, review, resolution_time_seconds: int = 0) -> str:
        from iris_core.hitl.models import HITLReview

        if not isinstance(review, HITLReview):
            review = HITLReview.from_dict(review)
        return self.record_raw(
            {
                "event_type": "hitl_resolved",
                "review_id": review.review_id,
                "status": review.status.value,
                "resolved_by": review.resolved_by,
                "reviewer_note": review.reviewer_note,
                "approval_token": review.approval_token,
                "resolution_time_seconds": resolution_time_seconds,
            }
        )

    def record_hitl_call_proceeded(
        self,
        review_id: str,
        approved_by: str,
        original_tool: str,
        original_action: str,
    ) -> str:
        return self.record_raw(
            {
                "event_type": "hitl_call_proceeded",
                "review_id": review_id,
                "approved_by": approved_by,
                "original_tool": original_tool,
                "original_action": original_action,
            }
        )

    def record_compliance_violation(
        self,
        rule_id: str,
        context,
        response: str,
    ) -> str:
        return self.record_raw(
            {
                "event_type": "compliance_violation",
                "rule_id": rule_id,
                "response": response,
                "action": getattr(context, "action", ""),
                "resource": getattr(context, "resource", ""),
                "environment": getattr(context, "environment", ""),
            }
        )

    def _read_jsonl(self, filename: str) -> List[dict]:
        path = self._dir / filename
        if not path.exists():
            return []
        entries: List[dict] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    @staticmethod
    def _parse_event_timestamp(timestamp: str) -> Optional[datetime]:
        if not timestamp:
            return None
        normalized = timestamp.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized.replace("+00:00", ""))
        except ValueError:
            return None

    def _event_age_days(self, timestamp: str, now: Optional[datetime] = None) -> Optional[int]:
        event_dt = self._parse_event_timestamp(timestamp)
        if event_dt is None:
            return None
        reference = now or datetime.utcnow()
        return (reference - event_dt).days

    def _oldest_event_age_days(self, now: Optional[datetime] = None) -> Optional[int]:
        events = self._read_jsonl("events.jsonl")
        ages = [
            age
            for event in events
            if (age := self._event_age_days(event.get("timestamp", ""), now=now)) is not None
        ]
        return max(ages) if ages else None

    def prune_old_events(self) -> int:
        """
        Remove events.jsonl entries older than FREE_RETENTION_DAYS.

        Idempotent — safe to run on every vault open. Skipped for Pro/Enterprise.
        assessments.jsonl is never modified.
        """
        if Entitlements().has(Feature.VAULT_UNLIMITED_RETENTION):
            return 0

        if not self._log_file.exists():
            return 0

        now = datetime.utcnow()
        cutoff = now - timedelta(days=self.FREE_RETENTION_DAYS)
        kept: List[dict] = []
        pruned = 0

        for event in self._read_jsonl("events.jsonl"):
            event_dt = self._parse_event_timestamp(event.get("timestamp", ""))
            if event_dt is None or event_dt >= cutoff:
                kept.append(event)
            else:
                pruned += 1

        if pruned:
            with open(self._log_file, "w") as f:
                for event in kept:
                    f.write(json.dumps(event) + "\n")

        return pruned

    def get_retention_warning(self) -> Optional[str]:
        """Warn when the oldest event is within 5 days of the free-tier retention limit."""
        if Entitlements().has(Feature.VAULT_UNLIMITED_RETENTION):
            return None

        oldest_age = self._oldest_event_age_days()
        if oldest_age is None or oldest_age < self.RETENTION_WARNING_DAYS:
            return None

        return (
            f"Your oldest governance events are {oldest_age} days old.\n"
            f"Free tier retains events for {self.FREE_RETENTION_DAYS} days.\n"
            "Upgrade to IRIS Pro for unlimited retention:\n"
            "iris license activate <your-key>"
        )

    @staticmethod
    def _parse_since(since: str) -> str:
        """Normalize a date or ISO timestamp for string comparison."""
        if len(since) <= 10:
            return f"{since}T00:00:00"
        return since

    def get_delegation_events(
        self,
        limit: int = 100,
        user_id: Optional[str] = None,
    ) -> List[dict]:
        """Return Evidence Vault entries for delegated agent actions."""
        events = [
            e
            for e in self._read_jsonl("events.jsonl")
            if e.get("event_type") == "delegated_call"
        ]
        if user_id:
            events = [e for e in events if e.get("acting_for_user") == user_id]
        return events[-limit:]

    def get_events(
        self,
        limit: int = 100,
        since: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> List[dict]:
        events = self._read_jsonl("events.jsonl")
        if since:
            since_norm = self._parse_since(since)
            events = [e for e in events if e.get("timestamp", "") >= since_norm]
        if severity:
            sev = severity.upper()
            events = [
                e
                for e in events
                if any(v.get("severity") == sev for v in e.get("violations", []))
            ]
        return events[-limit:]

    def get_violations(self, severity: Optional[str] = None) -> List[dict]:
        violations: List[dict] = []
        sev_filter = severity.upper() if severity else None
        for event in self._read_jsonl("events.jsonl"):
            for violation in event.get("violations", []):
                if sev_filter and violation.get("severity") != sev_filter:
                    continue
                violations.append(
                    {
                        **violation,
                        "event_id": event.get("event_id"),
                        "timestamp": event.get("timestamp"),
                        "action": event.get("action"),
                        "resource": event.get("resource"),
                        "environment": event.get("environment"),
                        "decision": event.get("decision"),
                    }
                )
        return violations

    def get_assessments(self) -> List[dict]:
        return self._read_jsonl("assessments.jsonl")

    def check_integrity(self, passport_assessment_id: Optional[str] = None) -> dict:
        """Verify vault entries are internally consistent."""
        issues: List[str] = []
        assessment_ids = {a.get("assessment_id") for a in self.get_assessments()}

        if passport_assessment_id and passport_assessment_id not in assessment_ids:
            issues.append(
                f"Passport assessment ID '{passport_assessment_id}' "
                "not found in assessments.jsonl"
            )

        for event in self._read_jsonl("events.jsonl"):
            for field in ("event_id", "timestamp", "agent_id", "decision"):
                if field not in event:
                    issues.append(
                        f"Event missing required field '{field}': "
                        f"{event.get('event_id', 'unknown')}"
                    )
            if event.get("agent_id") and event["agent_id"] != self._agent_id:
                issues.append(
                    f"Event {event.get('event_id')} agent_id mismatch: "
                    f"expected {self._agent_id}, got {event['agent_id']}"
                )

        return {"valid": len(issues) == 0, "issues": issues}

    @staticmethod
    def _days_until_annual_review(last_reviewed_at: Optional[str]) -> Optional[int]:
        if not last_reviewed_at:
            return None
        reviewed = datetime.fromisoformat(last_reviewed_at)
        days_since = (datetime.utcnow() - reviewed).days
        return 365 - days_since

    def _retention_days_remaining(self, now: Optional[datetime] = None) -> int:
        oldest_age = self._oldest_event_age_days(now=now)
        if oldest_age is None:
            return self.FREE_RETENTION_DAYS
        return max(0, self.FREE_RETENTION_DAYS - oldest_age)

    def get_summary(self, last_reviewed_at: Optional[str] = None) -> VaultSummary:
        events = self._read_jsonl("events.jsonl")
        assessments = self.get_assessments()

        violations_by_severity: Counter[str] = Counter()
        violations_by_rule: Counter[str] = Counter()
        environments: set[str] = set()
        cross_region_blocks = 0
        hitl_gates_triggered = 0
        events_with_violations = 0

        for event in events:
            env = event.get("environment")
            if env:
                environments.add(env)
            if event.get("decision") == "HITL":
                hitl_gates_triggered += 1
            event_violations = event.get("violations", [])
            if event_violations:
                events_with_violations += 1
            for violation in event_violations:
                violations_by_severity[violation.get("severity", "UNKNOWN")] += 1
                rule_id = violation.get("rule_id", "UNKNOWN")
                violations_by_rule[rule_id] += 1
                if rule_id == "IRIS-XR-001":
                    cross_region_blocks += 1

        total_evaluations = len(events)
        total_violation_entries = sum(violations_by_rule.values())
        pass_rate = (
            (total_evaluations - events_with_violations) / total_evaluations
            if total_evaluations
            else 1.0
        )

        most_violated = (
            violations_by_rule.most_common(1)[0][0] if violations_by_rule else None
        )

        last_assessment_date = None
        if assessments:
            sorted_assessments = sorted(
                assessments, key=lambda a: a.get("timestamp", ""), reverse=True
            )
            last_assessment_date = sorted_assessments[0].get("timestamp")

        upgrade_available = not Entitlements().has(Feature.VAULT_UNLIMITED_RETENTION)

        return VaultSummary(
            agent_id=self._agent_id,
            total_evaluations=total_evaluations,
            total_violations=total_violation_entries,
            violations_by_severity=dict(violations_by_severity),
            violations_by_rule=dict(violations_by_rule),
            most_violated_rule=most_violated,
            compliance_pass_rate=pass_rate,
            last_assessment_date=last_assessment_date,
            last_reviewed_at=last_reviewed_at,
            days_until_annual_review=self._days_until_annual_review(last_reviewed_at),
            environments_active=sorted(environments),
            cross_region_blocks=cross_region_blocks,
            hitl_gates_triggered=hitl_gates_triggered,
            retention_days_remaining=self._retention_days_remaining(),
            upgrade_available=upgrade_available,
        )

    def export_vault(self) -> dict:
        """Return the full vault contents for external audit tools."""
        summary = self.get_summary()
        return {
            "agent_id": self._agent_id,
            "exported_at": datetime.utcnow().isoformat(),
            "events": self._read_jsonl("events.jsonl"),
            "assessments": self.get_assessments(),
            "summary": {
                "agent_id": summary.agent_id,
                "total_evaluations": summary.total_evaluations,
                "total_violations": summary.total_violations,
                "violations_by_severity": summary.violations_by_severity,
                "violations_by_rule": summary.violations_by_rule,
                "most_violated_rule": summary.most_violated_rule,
                "compliance_pass_rate": summary.compliance_pass_rate,
                "last_assessment_date": summary.last_assessment_date,
                "environments_active": summary.environments_active,
                "cross_region_blocks": summary.cross_region_blocks,
                "hitl_gates_triggered": summary.hitl_gates_triggered,
                "retention_days_remaining": summary.retention_days_remaining,
                "upgrade_available": summary.upgrade_available,
            },
        }

    def check_for_breach_indicators(self) -> Optional[BreachNotification]:
        """
        Scan the last 24 hours for CRITICAL DLP response findings that were not blocked.

        These represent potential HIPAA/GDPR breach events where sensitive data may
        have reached an end user or external log.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=24)
        cutoff_iso = cutoff.isoformat()

        for event in reversed(self._read_jsonl("events.jsonl")):
            timestamp = event.get("timestamp", "")
            if timestamp < cutoff_iso:
                continue

            event_type = event.get("event_type", "")
            direction = event.get("direction", "")
            has_critical = event.get("has_critical", False)

            is_breach_event = event_type == "potential_data_breach"
            is_unblocked_dlp = (
                event_type == "dlp_response_scan"
                and direction == "response"
                and has_critical
                and event.get("action_taken") != "blocked"
            )
            if not is_breach_event and not is_unblocked_dlp:
                continue

            if is_breach_event and event.get("action_taken") == "blocked":
                continue

            patterns = event.get("phi_patterns") or event.get("pattern_ids") or []
            if not patterns and event.get("findings"):
                patterns = [f.get("pattern_id", "") for f in event["findings"]]

            detected_at = event.get("detected_at") or timestamp
            return BreachNotification(
                breach_id=event.get("breach_id") or event.get("event_id", ""),
                agent_name=event.get("agent_name") or self._agent_id,
                phi_patterns_detected=[p for p in patterns if p],
                detected_at=detected_at,
                iris_rule=event.get("iris_rule", "HIPAA-006"),
                gdpr_window=event.get("gdpr_window"),
                hipaa_window=event.get("hipaa_window"),
            )

        return None
