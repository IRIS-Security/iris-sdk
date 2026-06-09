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

echo "STEP 1: Discover ungoverned agents in an existing codebase"
echo "  Scanning the demo/customers/ directory..."
pause
iris scan --dir demo/customers --discover || true
pause

echo "STEP 2: Register a new agent for Apex Capital"
pause
iris register \
  --name apex-loan-processor \
  --owner platform@apexcapital.com \
  --team ai-platform \
  --compliance colorado-ai-act \
  --high-risk
pause

echo "STEP 3: Ask IRIS which regulations apply"
pause
# Q1 and Q5 prefilled from passport; answer remaining questions only:
# Q2=financial services, Q3=AWS, Q4=financial data, Q6=no (Enter),
# Q7=None of the above, Q8=Colorado
printf '4\n2\n2\n\n5\n1\n' | iris framework suggest --agent apex-loan-processor
pause

echo "STEP 4: Check compliance — watch it fail"
echo "  (This is expected — the agent is new and has no assessment)"
pause
iris compliance check --framework colorado-ai-act --agent apex-loan-processor </dev/null || true
pause

echo "STEP 5: Run the impact assessment"
echo "  (IRIS asks 8 questions and generates the CO-002 document)"
pause
iris compliance assess --agent apex-loan-processor --yes \
  --answers demo/scripts/demo_answers.json
pause

echo "STEP 6: Show the pre-built payment agent — already compliant"
pause
iris compliance check --framework colorado-ai-act \
  --dir demo/governance/agents --agent demo-payment-agent
pause

echo "STEP 7: Show the full audit trail"
pause
mkdir -p "$HOME/.iris/evidence/demo-payment-agent"
cp demo/governance/evidence/demo-payment-agent/*.jsonl \
  "$HOME/.iris/evidence/demo-payment-agent/"
iris evidence report --agent demo-payment-agent \
  --dir demo/governance/agents || \
  echo "Evidence report requires Pro tier for full detail."
pause

echo ""
echo "════════════════════════════════════════════════════"
echo "  Demo complete."
echo "  Install: pip install iris-security-sdk iris-security-cli"
echo "  GitHub:  github.com/gimartinb/iris-sdk"
echo "════════════════════════════════════════════════════"
