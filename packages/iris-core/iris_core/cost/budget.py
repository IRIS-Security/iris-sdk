"""Per-agent cost/token budget declared in passport.yaml — governed by Cedar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BudgetConfig:
    """Per-agent budget configuration. Stored in passport.yaml (spec.budget).

    One overage action, not two competing booleans — exceeding the budget
    is a single policy choice: route through HITL (step_up) or block
    outright (deny).
    """

    enabled: bool = False
    per_call_budget_usd: Optional[float] = None
    daily_budget_usd: Optional[float] = None
    on_overage: str = "step_up"  # "step_up" | "deny"

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "BudgetConfig":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            per_call_budget_usd=(
                float(data["per_call_budget_usd"])
                if data.get("per_call_budget_usd") is not None
                else None
            ),
            daily_budget_usd=(
                float(data["daily_budget_usd"])
                if data.get("daily_budget_usd") is not None
                else None
            ),
            on_overage=str(data.get("on_overage", "step_up")),
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "per_call_budget_usd": self.per_call_budget_usd,
            "daily_budget_usd": self.daily_budget_usd,
            "on_overage": self.on_overage,
        }
