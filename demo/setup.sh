#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo ""
echo "Setting up IRIS SE Demo Environment..."
echo ""

python3 --version || { echo "Python 3.10+ required"; exit 1; }

if [ -d "packages/iris-core" ]; then
  echo "Installing IRIS from local monorepo (editable)..."
  pip install -q -e packages/iris-core -e packages/iris-python -e packages/iris-scm -e apps/iris-cli
else
  echo "Installing IRIS from PyPI..."
  pip install iris-security-sdk iris-security-cli --quiet
fi

iris --version

ls demo/governance/agents/

# Seed Evidence Vault for demo-payment-agent audit trail
VAULT_DEST="$HOME/.iris/evidence/demo-payment-agent"
mkdir -p "$VAULT_DEST"
cp demo/governance/evidence/demo-payment-agent/*.jsonl "$VAULT_DEST/"

python3 demo/scripts/check_prerequisites.py

echo ""
echo "Setup complete. Run: bash demo/run_demo.sh"
