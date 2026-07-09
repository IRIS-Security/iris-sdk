#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PAUSE=${PAUSE:-true}

pause() {
  if [ "$PAUSE" = "true" ]; then
    echo ""
    read -p "  Press Enter to continue..." _
    echo ""
  fi
}

if [ -t 1 ]; then
  clear
fi
echo "════════════════════════════════════════════════════"
echo "  IRIS AI Agent Governance — Live Demo"
echo "════════════════════════════════════════════════════"
echo ""

echo "STEP 0: The brownfield moment — what does your codebase already have?"
echo "  Running discovery scan on demo/customers/meridian_health..."
pause
iris scan --dir demo/customers/meridian_health --discover || true
pause

echo "  IRIS found ungoverned agents. Let me show you the one-line fix."
pause
iris scan --dir demo/customers/meridian_health --discover --govern \
  --compliance colorado-ai-act --no-auto-apply --yes
pause

echo "STEP 1: Trust demonstration — what exactly does IRIS do?"
pause
iris explain
pause

echo "STEP 2: Register a new agent and get an opinionated action plan"
pause
iris register \
  --name apex-loan-processor \
  --owner platform@apexcapital.com \
  --team ai-platform \
  --compliance colorado-ai-act \
  --high-risk
pause
printf '4\n2\n2\n\n5\n1\n' | iris framework suggest --agent apex-loan-processor
pause

echo "STEP 3: Status check — the git status moment for compliance"
pause
iris status
pause

echo "STEP 4: Follow the action plan — assess and check compliance"
pause
iris compliance assess --agent apex-loan-processor --yes \
  --answers demo/scripts/demo_answers.json
iris compliance check --framework colorado-ai-act --agent apex-loan-processor </dev/null || true
pause

echo "STEP 5: Watch real-time decisions (sample from Evidence Vault)"
pause
iris watch --agent demo-payment-agent --tail 5 &
WATCH_PID=$!
sleep 2
kill $WATCH_PID 2>/dev/null || true
wait $WATCH_PID 2>/dev/null || true
pause

echo "STEP 6: Status after following the action plan"
pause
iris status
pause

echo "STEP 7: The fully compliant agent and audit trail"
pause
iris compliance check --framework colorado-ai-act \
  --dir demo/governance/agents --agent demo-payment-agent
mkdir -p "$HOME/.iris/evidence/demo-payment-agent"
cp demo/governance/evidence/demo-payment-agent/*.jsonl \
  "$HOME/.iris/evidence/demo-payment-agent/"
iris evidence report --agent demo-payment-agent \
  --dir demo/governance/agents
pause

echo ""
echo "════════════════════════════════════════════════════"
echo "  Demo complete."
echo "  Install: pip install iris-security-sdk iris-security-cli"
echo "  GitHub:  github.com/IRIS-Security/iris-sdk"
echo "════════════════════════════════════════════════════"
