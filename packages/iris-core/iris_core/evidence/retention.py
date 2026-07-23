"""Retention policy computation from ControlMapping attachments."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from iris_core.evidence.models import ControlMapping, RetentionPolicy

DEFAULT_RETENTION_DAYS = 365

CONTROL_RETENTION_DAYS: dict[str, int] = {
    "CO-RR-001": 1095,
    "LL144-005": 730,
    "NYC-LL144-005": 730,
    "PIPL-006": 1095,
    "CCPA-006": 1095,
    "HIPAA-001": 2190,
    "HIPAA-006": 2190,
    "HIPAA": 2190,
    "FEDRAMP-CONMON": 1095,
    "FEDRAMP-001": 1095,
}

FRAMEWORK_DEFAULT_RETENTION: dict[str, int] = {
    "colorado-ai-act": 1095,
    "nyc-ll144": 730,
    "china-pipl": 1095,
    "ccpa-admt": 1095,
    "hipaa": 2190,
    "fedramp": 1095,
    "aiuc-1": 365,
}


def retention_days_for_control(control_id: str, framework_id: str) -> int:
    if control_id in CONTROL_RETENTION_DAYS:
        return CONTROL_RETENTION_DAYS[control_id]
    if framework_id in FRAMEWORK_DEFAULT_RETENTION:
        return FRAMEWORK_DEFAULT_RETENTION[framework_id]
    return DEFAULT_RETENTION_DAYS


def compute_retention_policy(
    event_id: str,
    event_timestamp: str,
    mappings: Iterable[ControlMapping],
    *,
    deletion_hold: bool = False,
    erasure_requested: bool = False,
) -> RetentionPolicy:
    mapping_list = list(mappings)
    if mapping_list:
        retention_days = max(
            retention_days_for_control(m.control_id, m.framework_id)
            for m in mapping_list
        )
    else:
        retention_days = DEFAULT_RETENTION_DAYS

    ts = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00").replace("+00:00", ""))
    eligible_at = (ts + timedelta(days=retention_days)).isoformat()

    return RetentionPolicy(
        event_id=event_id,
        retention_days=retention_days,
        eligible_for_deletion_at=eligible_at,
        deletion_hold=deletion_hold,
        erasure_requested=erasure_requested,
    )
