"""Cost tracking storage, aggregation, and async recording."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from iris_core.cost.counter import TokenCounter
from iris_core.cost.pricing import PricingRegistry

logger = logging.getLogger("iris.cost")

_WRITE_LOCK = threading.Lock()


def costs_root() -> Path:
    return Path.home() / ".iris" / "costs"


@dataclass
class CostEntry:
    entry_id: str
    agent_id: str
    agent_name: str
    provider: str
    model: str
    tool_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    duration_ms: float
    environment: str
    timestamp: str
    is_estimated: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "CostEntry":
        return cls(
            entry_id=data["entry_id"],
            agent_id=data["agent_id"],
            agent_name=data.get("agent_name", data["agent_id"]),
            provider=data["provider"],
            model=data["model"],
            tool_name=data.get("tool_name", "unknown"),
            input_tokens=int(data["input_tokens"]),
            output_tokens=int(data["output_tokens"]),
            total_tokens=int(data.get("total_tokens", data["input_tokens"] + data["output_tokens"])),
            cost_usd=float(data["cost_usd"]),
            duration_ms=float(data.get("duration_ms", 0.0)),
            environment=data.get("environment", "dev"),
            timestamp=data["timestamp"],
            is_estimated=bool(data.get("is_estimated", False)),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CostAnomaly:
    type: str
    description: str
    call: CostEntry
    threshold_usd: float


@dataclass
class CostSummary:
    agent_id: str
    agent_name: str
    period_start: str
    period_end: str
    total_cost_usd: float
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    avg_cost_per_call: float
    avg_tokens_per_call: int
    most_expensive_call: Optional[CostEntry]
    most_expensive_tool: Optional[str]
    cost_by_model: Dict[str, float] = field(default_factory=dict)
    cost_by_tool: Dict[str, float] = field(default_factory=dict)
    cost_by_day: Dict[str, float] = field(default_factory=dict)
    estimated_monthly_cost: float = 0.0
    cost_trend: str = "STABLE"
    anomalies: List[CostAnomaly] = field(default_factory=list)


# Public alias used by SDK exports and CLI reports.
CostReport = CostSummary


class CostTracker:
    """Records every LLM call with token counts and estimated cost."""

    def __init__(self, agent_id: str, agent_name: str, costs_dir: Optional[Path] = None) -> None:
        self.agent_id = agent_id
        self.agent_name = agent_name
        self._dir = (costs_dir or costs_root()) / agent_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._dir / "costs.jsonl"

    @property
    def log_file(self) -> Path:
        return self._log_file

    def record(
        self,
        provider: str,
        model: str,
        tool_name: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        duration_ms: float,
        environment: str,
        timestamp: Optional[str] = None,
        is_estimated: bool = False,
    ) -> str:
        entry_id = str(uuid.uuid4())
        entry = CostEntry(
            entry_id=entry_id,
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            provider=provider,
            model=model,
            tool_name=tool_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            environment=environment,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            is_estimated=is_estimated,
        )
        with _WRITE_LOCK:
            with open(self._log_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.to_dict()) + "\n")
        return entry_id

    def get_entries(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> List[CostEntry]:
        if not self._log_file.exists():
            return []

        entries: List[CostEntry] = []
        for line in self._log_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = CostEntry.from_dict(json.loads(line))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

            if since and entry.timestamp < since:
                continue
            if until and entry.timestamp > until:
                continue
            if provider and entry.provider != provider:
                continue
            if model and entry.model != model:
                continue
            if tool_name and entry.tool_name != tool_name:
                continue
            entries.append(entry)
        return entries

    def get_summary(self, since: Optional[str] = None) -> CostSummary:
        entries = self.get_entries(since=since)
        if not entries:
            now = datetime.now(timezone.utc).isoformat()
            return CostSummary(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                period_start=since or now,
                period_end=now,
                total_cost_usd=0.0,
                total_calls=0,
                total_input_tokens=0,
                total_output_tokens=0,
                avg_cost_per_call=0.0,
                avg_tokens_per_call=0,
                most_expensive_call=None,
                most_expensive_tool=None,
            )

        period_start = since or min(e.timestamp for e in entries)
        period_end = max(e.timestamp for e in entries)
        total_cost = sum(e.cost_usd for e in entries)
        total_calls = len(entries)
        total_input = sum(e.input_tokens for e in entries)
        total_output = sum(e.output_tokens for e in entries)

        cost_by_model: Dict[str, float] = defaultdict(float)
        cost_by_tool: Dict[str, float] = defaultdict(float)
        cost_by_day: Dict[str, float] = defaultdict(float)
        tool_cost_counter: Counter[str] = Counter()

        most_expensive_call = max(entries, key=lambda e: e.cost_usd)
        for entry in entries:
            cost_by_model[entry.model] += entry.cost_usd
            cost_by_tool[entry.tool_name] += entry.cost_usd
            tool_cost_counter[entry.tool_name] += entry.cost_usd
            day_key = entry.timestamp[:10]
            cost_by_day[day_key] += entry.cost_usd

        most_expensive_tool = (
            tool_cost_counter.most_common(1)[0][0] if tool_cost_counter else None
        )

        estimated_monthly = _extrapolate_monthly_cost(entries, total_cost)
        cost_trend = _compute_cost_trend(cost_by_day)
        anomalies = detect_anomalies(entries)

        return CostSummary(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            period_start=period_start,
            period_end=period_end,
            total_cost_usd=round(total_cost, 6),
            total_calls=total_calls,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            avg_cost_per_call=round(total_cost / total_calls, 6) if total_calls else 0.0,
            avg_tokens_per_call=int((total_input + total_output) / total_calls) if total_calls else 0,
            most_expensive_call=most_expensive_call,
            most_expensive_tool=most_expensive_tool,
            cost_by_model=dict(cost_by_model),
            cost_by_tool=dict(cost_by_tool),
            cost_by_day=dict(sorted(cost_by_day.items())),
            estimated_monthly_cost=round(estimated_monthly, 6),
            cost_trend=cost_trend,
            anomalies=anomalies,
        )


# Prompt-waste advisory thresholds — flag, never rewrite.
_WASTE_RATIO_THRESHOLD = 20  # input:output tokens
_WASTE_MIN_INPUT_TOKENS = 500  # floor — don't flag small/trivial calls


def detect_anomalies(entries: List[CostEntry]) -> List[CostAnomaly]:
    """Flag unusually expensive or atypical LLM calls."""
    if not entries:
        return []

    anomalies: List[CostAnomaly] = []
    costs = [e.cost_usd for e in entries]
    median_cost = sorted(costs)[len(costs) // 2]
    model_counter = Counter(e.model for e in entries)
    dominant_model = model_counter.most_common(1)[0][0] if model_counter else None

    for entry in entries:
        if entry.input_tokens >= _WASTE_MIN_INPUT_TOKENS and (
            entry.output_tokens == 0
            or entry.input_tokens / entry.output_tokens > _WASTE_RATIO_THRESHOLD
        ):
            reasonable_input = entry.output_tokens * _WASTE_RATIO_THRESHOLD
            excess_input = max(entry.input_tokens - reasonable_input, 0)
            estimated_waste = PricingRegistry().calculate_cost(
                entry.provider, entry.model, excess_input, 0
            )
            ratio = (
                f"{entry.input_tokens // max(entry.output_tokens, 1)}:1"
                if entry.output_tokens
                else "∞:1 (no output)"
            )
            anomalies.append(
                CostAnomaly(
                    type="PROMPT_WASTE",
                    description=(
                        f"{entry.input_tokens:,} input tokens for {entry.output_tokens:,} "
                        f"output ({ratio}) — {entry.tool_name}(). Consider trimming context. "
                        f"Estimated waste: ${estimated_waste:.4f}"
                    ),
                    call=entry,
                    threshold_usd=estimated_waste,
                )
            )

        baseline = median_cost if median_cost > 0 else sum(costs) / len(costs)
        if entry.total_tokens > 50_000:
            anomalies.append(
                CostAnomaly(
                    type="SPIKE",
                    description=(
                        f"Prompt was {entry.total_tokens:,} tokens. Consider chunking the input."
                    ),
                    call=entry,
                    threshold_usd=50_000,
                )
            )

        if baseline > 0 and entry.cost_usd > baseline * 10:
            anomalies.append(
                CostAnomaly(
                    type="EXPENSIVE_CALL",
                    description=(
                        f"${entry.cost_usd:.4f} call — {entry.tool_name}() "
                        f"({entry.total_tokens:,} tokens)"
                    ),
                    call=entry,
                    threshold_usd=baseline * 10,
                )
            )

        if (
            dominant_model
            and entry.model != dominant_model
            and model_counter[entry.model] < len(entries) * 0.1
        ):
            anomalies.append(
                CostAnomaly(
                    type="UNUSUAL_MODEL",
                    description=(
                        f"Unusual model '{entry.model}' used by {entry.tool_name}()"
                    ),
                    call=entry,
                    threshold_usd=0.0,
                )
            )

    return anomalies


def _extrapolate_monthly_cost(entries: List[CostEntry], total_cost: float) -> float:
    if not entries:
        return 0.0
    timestamps = sorted(datetime.fromisoformat(e.timestamp.replace("Z", "+00:00")) for e in entries)
    span = (timestamps[-1] - timestamps[0]).total_seconds()
    if span <= 0:
        return total_cost
    daily_rate = total_cost / max(span / 86400, 1 / 24)
    return daily_rate * 30


def _compute_cost_trend(cost_by_day: Dict[str, float]) -> str:
    if len(cost_by_day) < 2:
        return "STABLE"
    days = sorted(cost_by_day.keys())
    midpoint = len(days) // 2
    first_half = sum(cost_by_day[d] for d in days[:midpoint])
    second_half = sum(cost_by_day[d] for d in days[midpoint:])
    if first_half == 0 and second_half == 0:
        return "STABLE"
    if second_half > first_half * 1.1:
        return "INCREASING"
    if second_half < first_half * 0.9:
        return "DECREASING"
    return "STABLE"


def discover_agent_trackers(root_dir: Optional[Path] = None) -> List[CostTracker]:
    """Find all agents with recorded cost data."""
    root = root_dir or costs_root()
    if not root.exists():
        return []

    trackers: List[CostTracker] = []
    for agent_dir in sorted(root.iterdir()):
        if not agent_dir.is_dir():
            continue
        log_file = agent_dir / "costs.jsonl"
        if not log_file.exists():
            continue
        agent_id = agent_dir.name
        agent_name = agent_id
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                agent_name = data.get("agent_name", agent_id)
                break
            except json.JSONDecodeError:
                continue
        trackers.append(CostTracker(agent_id=agent_id, agent_name=agent_name, costs_dir=root))
    return trackers


def _record_llm_cost_sync(
    agent_id: str,
    agent_name: str,
    provider: str,
    model: str,
    response: Any,
    tool_name: str,
    duration_ms: float,
    environment: str,
) -> None:
    counter = TokenCounter()
    input_tokens, output_tokens = counter.count_from_response(response, provider=provider, model=model)
    is_estimated = counter.last_is_estimated
    cost = PricingRegistry().calculate_cost(provider, model, input_tokens, output_tokens)
    tracker = CostTracker(agent_id=agent_id, agent_name=agent_name)
    tracker.record(
        provider=provider,
        model=model,
        tool_name=tool_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        duration_ms=duration_ms,
        environment=environment,
        is_estimated=is_estimated,
    )


def record_llm_cost_async(
    *,
    agent_id: str,
    agent_name: str,
    provider: str,
    model: str,
    response: Any,
    tool_name: str,
    duration_ms: float,
    environment: str,
) -> None:
    """Record LLM cost in a background thread — never blocks or raises."""

    def _worker() -> None:
        try:
            _record_llm_cost_sync(
                agent_id=agent_id,
                agent_name=agent_name,
                provider=provider,
                model=model,
                response=response,
                tool_name=tool_name,
                duration_ms=duration_ms,
                environment=environment,
            )
        except Exception as exc:
            logger.error("Cost tracking failed (non-fatal): %s", exc)

    thread = threading.Thread(target=_worker, daemon=True, name="iris-cost-record")
    thread.start()
