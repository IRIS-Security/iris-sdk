#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Remove any agents registered during the demo
rm -rf governance/agents/apex-loan-processor/
rm -rf governance/agents/meridian-patient-summarizer/
rm -rf governance/agents/demo-new-agent/

# Keep the pre-built demo agents in demo/governance/
echo "Demo environment reset. Ready to run again."
