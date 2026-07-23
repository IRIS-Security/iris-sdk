"""Local trust-state model — observation-only rolling-window read on
governance signals. See engine/cedar.py for how it's wired into evaluation."""

from iris_core.trust.state import (
    TrustState,
    TrustStateConfig,
    TrustStateResult,
    compute_trust_state,
    is_worse,
)

__all__ = [
    "TrustState",
    "TrustStateConfig",
    "TrustStateResult",
    "compute_trust_state",
    "is_worse",
]
