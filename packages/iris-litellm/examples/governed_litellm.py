#!/usr/bin/env python3
"""Derive IRIS workload profile from LiteLLM config or proxy."""

from __future__ import annotations

import argparse
import json

from iris_litellm import profile_from_litellm_config, profile_from_litellm_proxy
from iris_litellm.push import push_profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive IRIS workload profile from LiteLLM")
    parser.add_argument("--config", help="Path to litellm.config.yaml")
    parser.add_argument("--proxy", help="LiteLLM proxy base URL")
    parser.add_argument("--push", action="store_true", help="POST profile to IRIS Cloud when configured")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.config:
        profile = profile_from_litellm_config(args.config)
    elif args.proxy:
        profile = profile_from_litellm_proxy(args.proxy)
    else:
        parser.error("Provide --config or --proxy")

    if args.as_json:
        print(json.dumps(profile, indent=2))
    else:
        print("IRIS workload profile from LiteLLM:")
        for key, value in profile.items():
            print(f"  {key}: {value}")

    if args.push:
        print(push_profile(profile))


if __name__ == "__main__":
    main()
