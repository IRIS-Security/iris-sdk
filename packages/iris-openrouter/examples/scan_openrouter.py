"""Derive a WorkloadProfile from your OpenRouter activity.

This makes a LIVE call to https://openrouter.ai/api/v1/activity and needs an
OpenRouter Management API key (not your chat-completions key):

    export OPENROUTER_MANAGEMENT_KEY=...   # https://openrouter.ai/settings/management-keys
    python scan_openrouter.py
"""

from __future__ import annotations

import json
import sys

from iris_openrouter import (
    ManagementKeyError,
    OpenRouterActivityError,
    build_profile_from_activity,
    fetch_activity,
    summarize_activity,
)

try:
    rows = fetch_activity()
except (ManagementKeyError, OpenRouterActivityError) as exc:
    sys.exit(str(exc))

print(json.dumps(build_profile_from_activity(rows), indent=2))
for item in summarize_activity(rows):
    print(f"{item['requests']:>8}  {item['model']}  via {item['provider']}")
