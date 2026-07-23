"""Compliance drift detection — snapshots and posture change analysis."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from iris_core.compliance.registry import ComplianceRegistry
from iris_core.models.passport import AgentPassport

MAX_SNAPSHOTS = 30
DEFAULT_FRAMEWORKS = ("colorado-ai-act", "nist-ai-rmf")
TRACKED_FILES = ("passport.yaml", "policy.cedar", "policy-intent.md")


def default_snapshot_dir() -> Path:
    return Path.home() / ".iris" / "snapshots"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _md5_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.md5(path.read_bytes()).hexdigest()


def _colorado_controls_passed(passport: AgentPassport, agent_dir: Path) -> Tuple[int, int]:
    checks = [
        bool(passport.is_high_risk_ai and passport.agent_id),
        bool(passport.evidence_vault_id),
        bool(passport.intent_ref),
        (agent_dir / "policy.cedar").exists(),
        bool(passport.last_reviewed_at),
        (agent_dir / "impact-assessment.md").exists(),
    ]
    return sum(1 for c in checks if c), 6


def _nist_controls_passed(passport: AgentPassport, agent_dir: Path) -> Tuple[int, int]:
    if (agent_dir / "nist-ai-rmf-results.json").exists():
        return 24, 24
    return 0, 24


def compliance_score(passport: AgentPassport, agent_dir: Path, framework: str) -> float:
    if framework == "colorado-ai-act":
        satisfied, total = _colorado_controls_passed(passport, agent_dir)
        return satisfied / total if total else 0.0
    if framework == "nist-ai-rmf":
        satisfied, total = _nist_controls_passed(passport, agent_dir)
        return satisfied / total if total else 0.0
    return 0.0


def _cost_anomaly_ids(passport: AgentPassport, fallback_name: str) -> List[str]:
    """Cost anomalies for this agent, as entry_id strings — mirrors
    `violations: List[str]` (rule_id strings), diffed the same way. Never
    raises: cost tracking is optional and must not break drift snapshots."""
    try:
        from iris_core.cost.tracker import CostTracker, detect_anomalies

        tracker = CostTracker(passport.agent_id, passport.name or fallback_name)
        anomalies = detect_anomalies(tracker.get_entries())
        return sorted({a.call.entry_id for a in anomalies})
    except Exception:
        return []


def _frameworks_for_agent(passport: AgentPassport) -> List[str]:
    tags = [t.value for t in passport.compliance_tags]
    if not tags:
        tags = ["colorado-ai-act"]
    if "nist-ai-rmf" not in tags:
        tags = list(tags) + ["nist-ai-rmf"]
    return tags


@dataclass
class AgentSnapshot:
    agent_name: str
    passport_hash: str
    policy_hash: str
    compliance_scores: Dict[str, float]
    violations: List[str]
    is_production_ready: bool
    # Parallel, sibling field to `violations` — cost anomalies are not
    # regulatory-framework violations (ComplianceRegistry.check_passport()
    # populates `violations`), so this is diffed separately rather than
    # shoehorned into the compliance-rule model.
    cost_anomalies: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentSnapshot":
        return cls(**data)


@dataclass
class ComplianceSnapshot:
    timestamp: str
    agents: Dict[str, AgentSnapshot]

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "agents": {k: v.to_dict() for k, v in self.agents.items()}}

    @classmethod
    def from_dict(cls, data: dict) -> "ComplianceSnapshot":
        agents = {name: AgentSnapshot.from_dict(agent) for name, agent in data.get("agents", {}).items()}
        return cls(timestamp=data["timestamp"], agents=agents)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "ComplianceSnapshot":
        return cls.from_dict(json.loads(raw))


@dataclass
class DriftEvent:
    agent_name: str
    rule_id: str
    severity: str
    description: str
    change_type: str
    detected_at: str
    likely_cause: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoreChange:
    agent_name: str
    framework: str
    previous_score: float
    current_score: float
    delta: float
    direction: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DriftReport:
    generated_at: str
    comparison_period: str
    new_violations: List[DriftEvent] = field(default_factory=list)
    resolved_violations: List[DriftEvent] = field(default_factory=list)
    score_changes: List[ScoreChange] = field(default_factory=list)
    agents_degraded: List[str] = field(default_factory=list)
    agents_improved: List[str] = field(default_factory=list)
    net_score_change: float = 0.0
    summary: str = ""
    production_ready_lost: List[str] = field(default_factory=list)
    # Cost-anomaly as a governance/drift signal (Phase 6b) — a parallel
    # diff, not folded into new_violations/resolved_violations (those are
    # regulatory-framework-typed; cost anomalies aren't a regulatory rule).
    new_cost_anomalies: List[DriftEvent] = field(default_factory=list)
    resolved_cost_anomalies: List[DriftEvent] = field(default_factory=list)

    def has_degradation(self) -> bool:
        return bool(
            self.new_violations
            or self.agents_degraded
            or self.production_ready_lost
            or self.net_score_change < 0
            or self.new_cost_anomalies
        )

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "comparison_period": self.comparison_period,
            "new_violations": [e.to_dict() for e in self.new_violations],
            "resolved_violations": [e.to_dict() for e in self.resolved_violations],
            "score_changes": [s.to_dict() for s in self.score_changes],
            "agents_degraded": self.agents_degraded,
            "agents_improved": self.agents_improved,
            "net_score_change": self.net_score_change,
            "summary": self.summary,
            "production_ready_lost": self.production_ready_lost,
            "new_cost_anomalies": [e.to_dict() for e in self.new_cost_anomalies],
            "resolved_cost_anomalies": [e.to_dict() for e in self.resolved_cost_anomalies],
        }


class DriftDetector:
    """Detects compliance posture changes between snapshots."""

    def __init__(self, governance_dir: Path, snapshot_dir: Path | None = None) -> None:
        self.governance_dir = Path(governance_dir)
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else default_snapshot_dir()
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._registry = ComplianceRegistry()

    def _discover_agent_dirs(self) -> Dict[str, Path]:
        agents: Dict[str, Path] = {}
        if not self.governance_dir.exists():
            return agents
        for passport_file in sorted(self.governance_dir.rglob("passport.yaml")):
            try:
                passport = AgentPassport.from_yaml(passport_file.read_text())
                if passport.name:
                    agents[passport.name] = passport_file.parent
            except Exception:
                continue
        return agents

    def _build_agent_snapshot(self, name: str, agent_dir: Path) -> AgentSnapshot:
        passport = AgentPassport.from_yaml((agent_dir / "passport.yaml").read_text())
        frameworks = _frameworks_for_agent(passport)
        scores = {fw: compliance_score(passport, agent_dir, fw) for fw in frameworks}
        violations = self._registry.check_passport(passport, "colorado-ai-act")
        violation_ids = sorted({v.rule_id for v in violations})
        prod_ready = compliance_score(passport, agent_dir, "colorado-ai-act") >= 1.0 and not violations
        return AgentSnapshot(
            agent_name=name,
            passport_hash=_md5_file(agent_dir / "passport.yaml"),
            policy_hash=_md5_file(agent_dir / "policy.cedar"),
            compliance_scores=scores,
            violations=violation_ids,
            is_production_ready=prod_ready,
            cost_anomalies=_cost_anomaly_ids(passport, name),
        )

    def _current_snapshot(self) -> ComplianceSnapshot:
        agents = {
            name: self._build_agent_snapshot(name, agent_dir)
            for name, agent_dir in self._discover_agent_dirs().items()
        }
        return ComplianceSnapshot(timestamp=_utc_now_iso(), agents=agents)

    def _prune_old_snapshots(self) -> None:
        files = sorted(self.snapshot_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(files) > MAX_SNAPSHOTS:
            files.pop(0).unlink(missing_ok=True)

    def take_snapshot(self, output_path: Path | None = None) -> ComplianceSnapshot:
        snapshot = self._current_snapshot()
        dest = output_path or (self.snapshot_dir / f"{snapshot.timestamp.replace(':', '-')}.json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(snapshot.to_json())
        if output_path is None:
            self._prune_old_snapshots()
        return snapshot

    def list_snapshots(self) -> List[Path]:
        return sorted(self.snapshot_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)

    def _load_snapshot_file(self, path: Path) -> ComplianceSnapshot:
        return ComplianceSnapshot.from_json(path.read_text())

    def _resolve_baseline(self, since: str | None) -> Tuple[ComplianceSnapshot | None, str]:
        if since:
            since_path = Path(since)
            if since_path.exists() and since_path.suffix == ".json":
                snap = self._load_snapshot_file(since_path)
                return snap, f"since {snap.timestamp}"

            snapshots = self.list_snapshots()
            if not snapshots:
                return None, "no baseline"

            target = since.replace(":", "-")
            best: Path | None = None
            best_delta = None
            for path in snapshots:
                try:
                    snap = self._load_snapshot_file(path)
                    ts = snap.timestamp
                except (json.JSONDecodeError, KeyError):
                    continue
                try:
                    snap_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                    delta = abs((snap_dt - since_dt).total_seconds())
                except ValueError:
                    if target in path.name:
                        return self._load_snapshot_file(path), f"since {since}"
                    continue
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best = path
            if best:
                snap = self._load_snapshot_file(best)
                return snap, f"since {snap.timestamp}"
            return None, f"since {since}"

        snapshots = self.list_snapshots()
        if not snapshots:
            return None, "no baseline"
        snap = self._load_snapshot_file(snapshots[-1])
        return snap, f"since {snap.timestamp}"

    def _violation_details(self, agent_name: str, rule_id: str) -> Tuple[str, str]:
        agent_dir = self._discover_agent_dirs().get(agent_name)
        if not agent_dir:
            return "HIGH", rule_id
        passport = AgentPassport.from_yaml((agent_dir / "passport.yaml").read_text())
        for v in self._registry.check_passport(passport, "colorado-ai-act"):
            if v.rule_id == rule_id:
                return v.severity.value, v.message
        return "HIGH", rule_id

    def _cost_anomaly_details(self, agent_name: str, entry_id: str) -> Tuple[str, str]:
        agent_dir = self._discover_agent_dirs().get(agent_name)
        if not agent_dir:
            return "MEDIUM", entry_id
        try:
            from iris_core.cost.tracker import CostTracker, detect_anomalies

            passport = AgentPassport.from_yaml((agent_dir / "passport.yaml").read_text())
            tracker = CostTracker(passport.agent_id, passport.name or agent_name)
            for anomaly in detect_anomalies(tracker.get_entries()):
                if anomaly.call.entry_id == entry_id:
                    return anomaly.type, anomaly.description
        except Exception:
            pass
        return "MEDIUM", entry_id

    def _format_time_ago(self, mtime: float) -> str:
        delta = datetime.now(timezone.utc).timestamp() - mtime
        if delta < 3600:
            mins = max(1, int(delta / 60))
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        if delta < 86400:
            hours = max(1, int(delta / 3600))
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = max(1, int(delta / 86400))
        return f"{days} day{'s' if days != 1 else ''} ago"

    def _likely_cause(self, agent_name: str, agent_dir: Path | None, baseline: AgentSnapshot | None) -> str:
        if agent_dir is None:
            return "new agent registered without impact assessment"

        file_mtimes: List[Tuple[str, float]] = []
        for filename in TRACKED_FILES:
            path = agent_dir / filename
            if path.exists():
                file_mtimes.append((filename, path.stat().st_mtime))

        if not file_mtimes:
            if baseline is None:
                return "new agent registered without impact assessment"
            return "agent configuration changed"

        filename, mtime = max(file_mtimes, key=lambda item: item[1])
        ago = self._format_time_ago(mtime)

        if filename == "passport.yaml":
            if baseline and baseline.passport_hash != _md5_file(agent_dir / "passport.yaml"):
                return f"passport.yaml was modified {ago}"
            return f"passport.yaml was modified {ago}"
        if filename == "policy.cedar":
            return f"policy.cedar was recompiled {ago}"
        if filename == "policy-intent.md":
            if not (agent_dir / "policy-intent.md").exists():
                return f"policy-intent.md was deleted {ago}"
            return f"policy-intent.md was modified {ago}"
        return f"{filename} was modified {ago}"

    def detect_drift(self, since: str | None = None) -> DriftReport:
        current = self._current_snapshot()
        baseline, period = self._resolve_baseline(since)
        generated_at = _utc_now_iso()
        agent_dirs = self._discover_agent_dirs()

        if baseline is None:
            return DriftReport(
                generated_at=generated_at,
                comparison_period="baseline established",
                summary=(
                    "No prior snapshot found. A baseline snapshot was not compared. "
                    "Run iris drift check again after changes to detect drift."
                ),
            )

        new_violations: List[DriftEvent] = []
        resolved_violations: List[DriftEvent] = []
        score_changes: List[ScoreChange] = []
        agents_degraded: List[str] = []
        agents_improved: List[str] = []
        production_ready_lost: List[str] = []
        new_cost_anomalies: List[DriftEvent] = []
        resolved_cost_anomalies: List[DriftEvent] = []

        all_agent_names = sorted(set(baseline.agents) | set(current.agents))

        for name in all_agent_names:
            prev = baseline.agents.get(name)
            curr = current.agents.get(name)
            agent_dir = agent_dirs.get(name)

            if prev is None and curr is not None:
                for rule_id in curr.violations:
                    severity, description = self._violation_details(name, rule_id)
                    new_violations.append(
                        DriftEvent(
                            agent_name=name,
                            rule_id=rule_id,
                            severity=severity,
                            description=description,
                            change_type="appeared",
                            detected_at=generated_at,
                            likely_cause=self._likely_cause(name, agent_dir, None),
                        )
                    )
                if not curr.is_production_ready:
                    production_ready_lost.append(name)
                for entry_id in curr.cost_anomalies:
                    anomaly_type, description = self._cost_anomaly_details(name, entry_id)
                    new_cost_anomalies.append(
                        DriftEvent(
                            agent_name=name,
                            rule_id=entry_id,
                            severity=anomaly_type,
                            description=description,
                            change_type="appeared",
                            detected_at=generated_at,
                            likely_cause=self._likely_cause(name, agent_dir, None),
                        )
                    )
                continue

            if curr is None:
                continue

            prev_violations = set(prev.violations)
            curr_violations = set(curr.violations)
            prev_cost_anomalies = set(prev.cost_anomalies)
            curr_cost_anomalies = set(curr.cost_anomalies)

            for entry_id in sorted(curr_cost_anomalies - prev_cost_anomalies):
                anomaly_type, description = self._cost_anomaly_details(name, entry_id)
                new_cost_anomalies.append(
                    DriftEvent(
                        agent_name=name,
                        rule_id=entry_id,
                        severity=anomaly_type,
                        description=description,
                        change_type="appeared",
                        detected_at=generated_at,
                        likely_cause=self._likely_cause(name, agent_dir, prev),
                    )
                )

            for entry_id in sorted(prev_cost_anomalies - curr_cost_anomalies):
                anomaly_type, description = self._cost_anomaly_details(name, entry_id)
                resolved_cost_anomalies.append(
                    DriftEvent(
                        agent_name=name,
                        rule_id=entry_id,
                        severity=anomaly_type,
                        description=description,
                        change_type="resolved",
                        detected_at=generated_at,
                        likely_cause=self._likely_cause(name, agent_dir, prev),
                    )
                )

            for rule_id in sorted(curr_violations - prev_violations):
                severity, description = self._violation_details(name, rule_id)
                new_violations.append(
                    DriftEvent(
                        agent_name=name,
                        rule_id=rule_id,
                        severity=severity,
                        description=description,
                        change_type="appeared",
                        detected_at=generated_at,
                        likely_cause=self._likely_cause(name, agent_dir, prev),
                    )
                )

            for rule_id in sorted(prev_violations - curr_violations):
                severity, description = self._violation_details(name, rule_id)
                resolved_violations.append(
                    DriftEvent(
                        agent_name=name,
                        rule_id=rule_id,
                        severity=severity,
                        description=description,
                        change_type="resolved",
                        detected_at=generated_at,
                        likely_cause=self._likely_cause(name, agent_dir, prev),
                    )
                )

            if prev.is_production_ready and not curr.is_production_ready:
                production_ready_lost.append(name)

            frameworks = sorted(set(prev.compliance_scores) | set(curr.compliance_scores))
            agent_delta = 0.0
            for fw in frameworks:
                previous_score = prev.compliance_scores.get(fw, 0.0)
                current_score = curr.compliance_scores.get(fw, 0.0)
                delta = current_score - previous_score
                if abs(delta) < 1e-9:
                    continue
                direction = "improved" if delta > 0 else "degraded"
                score_changes.append(
                    ScoreChange(
                        agent_name=name,
                        framework=fw,
                        previous_score=previous_score,
                        current_score=current_score,
                        delta=delta,
                        direction=direction,
                    )
                )
                agent_delta += delta

            if agent_delta < -1e-9:
                agents_degraded.append(name)
            elif agent_delta > 1e-9:
                agents_improved.append(name)

        net_delta = 0.0
        if score_changes:
            net_delta = sum(s.delta for s in score_changes) / len(score_changes)

        summary = self._build_summary(
            period,
            new_violations,
            resolved_violations,
            score_changes,
            production_ready_lost,
            net_delta,
        )

        return DriftReport(
            generated_at=generated_at,
            comparison_period=period,
            new_violations=new_violations,
            resolved_violations=resolved_violations,
            score_changes=score_changes,
            agents_degraded=sorted(set(agents_degraded)),
            agents_improved=sorted(set(agents_improved)),
            net_score_change=net_delta,
            summary=summary,
            production_ready_lost=production_ready_lost,
            new_cost_anomalies=new_cost_anomalies,
            resolved_cost_anomalies=resolved_cost_anomalies,
        )

    def _build_summary(
        self,
        period: str,
        new_violations: List[DriftEvent],
        resolved_violations: List[DriftEvent],
        score_changes: List[ScoreChange],
        production_ready_lost: List[str],
        net_delta: float,
    ) -> str:
        parts: List[str] = []
        if new_violations:
            parts.append(
                f"{len(new_violations)} new violation{'s' if len(new_violations) != 1 else ''} appeared"
            )
        if resolved_violations:
            parts.append(
                f"{len(resolved_violations)} violation{'s' if len(resolved_violations) != 1 else ''} resolved"
            )
        if production_ready_lost:
            parts.append(
                f"{len(production_ready_lost)} agent{'s' if len(production_ready_lost) != 1 else ''} "
                "no longer production-ready"
            )
        degraded_scores = [s for s in score_changes if s.direction == "degraded"]
        if degraded_scores:
            worst = min(degraded_scores, key=lambda s: s.delta)
            parts.append(
                f"{worst.framework} score dropped from {int(worst.previous_score * 100)}% "
                f"to {int(worst.current_score * 100)}%"
            )
        if not parts:
            if net_delta > 0:
                return f"Compliance posture improved {period}. No degradations detected."
            return f"No compliance changes detected {period}."
        direction = "degraded" if (new_violations or production_ready_lost or net_delta < 0) else "changed"
        return f"Your AI governance posture {direction} {period}: " + "; ".join(parts) + "."

    def generate_alert(self, report: DriftReport) -> str | None:
        if not report.has_degradation():
            return None

        lines = [
            "IRIS Compliance Drift Alert",
            "Your AI governance posture degraded since the last snapshot.",
        ]

        if report.new_violations:
            lines.append(f"{len(report.new_violations)} new violation{'s' if len(report.new_violations) != 1 else ''} detected:")
            for event in report.new_violations:
                sev = event.severity.ljust(8)
                lines.append(f"[{sev}] {event.agent_name}: {event.rule_id} — {event.description}")
                lines.append(f"Likely cause: {event.likely_cause}")

        if report.production_ready_lost:
            lines.append(
                f"{len(report.production_ready_lost)} agent{'s' if len(report.production_ready_lost) != 1 else ''} "
                "is no longer production-ready:"
            )
            for name in report.production_ready_lost:
                lines.append(f"{name} (was: READY, now: NOT READY)")

        degraded_scores = [s for s in report.score_changes if s.direction == "degraded"]
        for change in degraded_scores:
            fw_label = change.framework.replace("-", " ").upper()
            if change.framework == "nist-ai-rmf":
                fw_label = "NIST AI RMF"
            elif change.framework == "colorado-ai-act":
                fw_label = "Colorado AI Act"
            prev_pct = int(change.previous_score * 100)
            curr_pct = int(change.current_score * 100)
            delta_pct = int(change.delta * 100)
            lines.append(f"{fw_label} score: {prev_pct}% → {curr_pct}% ({delta_pct:+d}%)")

        lines.extend(
            [
                "Run: iris status",
                "Run: iris compliance check --framework colorado-ai-act",
                "Details: iris drift report",
            ]
        )
        return "\n".join(lines)


@dataclass
class IntentDriftEvent:
    session_id: str
    agent_id: str
    original_intent: str
    current_action: str
    semantic_distance: float
    drift_threshold: float
    flagged: bool
    timestamp: str


class SessionIntentTracker:
    """
    Tracks semantic drift of agent actions from original intent
    across a session. Called by CedarEngine on each action evaluation.

    AARM R7: semantic distance tracking.
    """

    def __init__(self, session_id: str, agent_id: str, original_intent: str):
        self.session_id = session_id
        self.agent_id = agent_id
        self.original_intent = original_intent
        self.actions_seen: List[str] = []
        self.drift_events: List[IntentDriftEvent] = []

    def evaluate(self, action: str) -> IntentDriftEvent:
        """
        Compute semantic distance between action and original intent.

        Uses keyword overlap as a lightweight proxy for semantic
        distance (no LLM call — must be sub-millisecond).

        Production upgrade path: swap for embedding similarity.
        """
        intent_keywords = set(self.original_intent.lower().split())
        action_keywords = set(
            action.lower().replace("/", " ").replace(":", " ").split()
        )

        if not intent_keywords:
            distance = 0.0
        else:
            overlap = len(intent_keywords & action_keywords)
            distance = 1.0 - (overlap / len(intent_keywords))

        if len(self.actions_seen) >= 3:
            recent = self.actions_seen[-3:]
            avg_recent_distance = sum(
                1.0
                - len(intent_keywords & set(a.lower().split()))
                / max(1, len(intent_keywords))
                for a in recent
            ) / 3
            distance = 0.6 * distance + 0.4 * avg_recent_distance

        self.actions_seen.append(action)
        threshold = 0.7
        event = IntentDriftEvent(
            session_id=self.session_id,
            agent_id=self.agent_id,
            original_intent=self.original_intent,
            current_action=action,
            semantic_distance=round(distance, 3),
            drift_threshold=threshold,
            flagged=distance > threshold,
            timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        self.drift_events.append(event)
        return event

    def summary(self) -> dict:
        flagged = [e for e in self.drift_events if e.flagged]
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "total_actions": len(self.actions_seen),
            "drift_events": len(flagged),
            "max_distance": max(
                (e.semantic_distance for e in self.drift_events), default=0
            ),
            "drift_flagged": len(flagged) > 0,
            "aarm_r7": True,
        }


@dataclass
class IntentDriftEvent:
    session_id: str
    agent_id: str
    original_intent: str
    current_action: str
    semantic_distance: float
    drift_threshold: float
    flagged: bool
    timestamp: str


class SessionIntentTracker:
    """
    Tracks semantic drift of agent actions from original intent
    across a session. Called by CedarEngine on each action evaluation.

    AARM R7: semantic distance tracking.
    """

    def __init__(self, session_id: str, agent_id: str, original_intent: str):
        self.session_id = session_id
        self.agent_id = agent_id
        self.original_intent = original_intent
        self.actions_seen: List[str] = []
        self.drift_events: List[IntentDriftEvent] = []

    def evaluate(self, action: str) -> IntentDriftEvent:
        """
        Compute semantic distance between action and original intent.

        Uses keyword overlap as a lightweight proxy for semantic
        distance (no LLM call — must be sub-millisecond).

        Production upgrade path: swap for embedding similarity.
        """
        intent_keywords = set(self.original_intent.lower().split())
        action_keywords = set(
            action.lower().replace("/", " ").replace(":", " ").split()
        )

        if not intent_keywords:
            distance = 0.0
        else:
            overlap = len(intent_keywords & action_keywords)
            distance = 1.0 - (overlap / len(intent_keywords))

        if len(self.actions_seen) >= 3:
            recent = self.actions_seen[-3:]
            avg_recent_distance = sum(
                1.0
                - len(intent_keywords & set(a.lower().split()))
                / max(1, len(intent_keywords))
                for a in recent
            ) / 3
            distance = 0.6 * distance + 0.4 * avg_recent_distance

        self.actions_seen.append(action)
        threshold = 0.7
        event = IntentDriftEvent(
            session_id=self.session_id,
            agent_id=self.agent_id,
            original_intent=self.original_intent,
            current_action=action,
            semantic_distance=round(distance, 3),
            drift_threshold=threshold,
            flagged=distance > threshold,
            timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        self.drift_events.append(event)
        return event

    def summary(self) -> dict:
        flagged = [e for e in self.drift_events if e.flagged]
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "total_actions": len(self.actions_seen),
            "drift_events": len(flagged),
            "max_distance": max(
                (e.semantic_distance for e in self.drift_events), default=0
            ),
            "drift_flagged": len(flagged) > 0,
            "aarm_r7": True,
        }
