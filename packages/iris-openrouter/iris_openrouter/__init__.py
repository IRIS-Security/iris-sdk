"""
IRIS OpenRouter integration — derive compliance workload profiles from
OpenRouter usage activity.

LIVE NETWORK CALL: this package calls GET https://openrouter.ai/api/v1/activity
with an OpenRouter Management API key (not the inference key used for chat
completions). It is not an offline check.

OSS/PAID CLASSIFICATION (P59):
  READ logic (OpenRouter activity -> WorkloadProfile)  -> OSS. Adoption hook.
  profile_from_openrouter() returning dict to caller   -> OSS.
  push_profile() POST /intelligence/profile/scan       -> OSS client; endpoint
      gated cloud-side by compliance_full_eval (402 if unentitled).
  Continuous tracking / org-wide model exposure over
  time / posture-over-time                              -> PAID, CLOUD ONLY.
      This package takes a point-in-time snapshot (OpenRouter's last 30
      completed UTC days) and stops.
"""

from __future__ import annotations

from iris_openrouter._profile import build_profile_from_activity, summarize_activity
from iris_openrouter.reader import (
    ManagementKeyError,
    OpenRouterActivityError,
    fetch_activity,
    profile_from_openrouter,
)

__version__ = "0.1.0"

__all__ = [
    "ManagementKeyError",
    "OpenRouterActivityError",
    "build_profile_from_activity",
    "fetch_activity",
    "profile_from_openrouter",
    "summarize_activity",
]
