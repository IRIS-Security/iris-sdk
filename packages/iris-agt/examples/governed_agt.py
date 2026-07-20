#!/usr/bin/env python3
"""Read an AGT audit-trail export and derive an IRIS workload profile."""

from __future__ import annotations

import argparse
import json

from iris_agt import profile_from_agt
from iris_agt.push import push_profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive IRIS workload profile from an AGT audit trail")
    parser.add_argument("audit_file", help="Path to AGT's audit_trail.jsonl (or a JSON export)")
    parser.add_argument("--no-verify-chain", action="store_true", help="Skip previous_hash continuity check")
    parser.add_argument("--push", action="store_true", help="POST profile to IRIS Cloud when configured")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    profile = profile_from_agt(args.audit_file, verify_chain=not args.no_verify_chain)
    if args.as_json:
        print(json.dumps(profile, indent=2))
    else:
        print("IRIS workload profile from AGT audit trail:")
        for key, value in profile.items():
            print(f"  {key}: {value}")

    if args.push:
        print(push_profile(profile))


if __name__ == "__main__":
    main()
