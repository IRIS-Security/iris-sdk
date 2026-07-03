#!/usr/bin/env python3
"""Read Langfuse project history and derive an IRIS workload profile."""

from __future__ import annotations

import argparse
import json

from iris_langfuse import profile_from_langfuse
from iris_langfuse.push import push_profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive IRIS workload profile from Langfuse")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--push", action="store_true", help="POST profile to IRIS Cloud when configured")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    profile = profile_from_langfuse(lookback_days=args.lookback_days)
    if args.as_json:
        print(json.dumps(profile, indent=2))
    else:
        print("IRIS workload profile from Langfuse:")
        for key, value in profile.items():
            print(f"  {key}: {value}")

    if args.push:
        print(push_profile(profile))


if __name__ == "__main__":
    main()
