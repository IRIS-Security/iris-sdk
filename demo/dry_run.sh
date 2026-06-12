#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# IRIS Demo Dry Run Script
# Run this BEFORE every customer, investor, or design partner call.
# If anything fails, fix it before the call. Never demo a broken step.
# ═══════════════════════════════════════════════════════════════════════

set -o pipefail
PASS=0; FAIL=0; WARN=0
DEMO_DIR="$HOME/iris-sdk"

green()  { echo -e "\033[32m  ✓ $1\033[0m"; PASS=$((PASS+1)); }
red()    { echo -e "\033[31m  ✗ $1\033[0m"; FAIL=$((FAIL+1)); }
yellow() { echo -e "\033[33m  ⚠ $1\033[0m"; WARN=$((WARN+1)); }
blue()   { echo -e "\033[34m\n▶ $1\033[0m"; }
header() { echo -e "\n\033[1m$1\033[0m"; echo "$(printf '═%.0s' {1..60})"; }

clear
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   IRIS Demo Dry Run — Pre-Call Verification  ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ── Prerequisites ─────────────────────────────────────────────────────
header "1. Prerequisites"

cd "$DEMO_DIR" 2>/dev/null || { red "Cannot cd to $DEMO_DIR — is the repo cloned?"; exit 1; }
green "In $DEMO_DIR"

iris --version > /tmp/iris_ver.txt 2>&1
[[ $? -eq 0 ]] && green "iris CLI: $(cat /tmp/iris_ver.txt)" || red "iris CLI not found — run: pip install iris-security-cli"

python3 -c "import iris" 2>/dev/null && green "iris-security-sdk installed" || red "iris-security-sdk missing — run: pip install iris-security-sdk"

python3 -c "from iris_core.dlp import DLPScanner" 2>/dev/null && green "DLP scanner available" || red "DLP scanner missing"

[[ -n "$ANTHROPIC_API_KEY" ]] && green "ANTHROPIC_API_KEY set" || \
  { [[ -n "$OPENAI_API_KEY" ]] && green "OPENAI_API_KEY set" || yellow "No LLM API key set — iris policy compile will not work"; }

[[ -f "demo/run_demo.sh" ]] && green "Demo scripts exist" || red "demo/run_demo.sh missing — run Cursor SE demo prompt"

[[ -f "demo/governance/agents/demo-payment-agent/passport.yaml" ]] \
  && green "demo-payment-agent passport exists" \
  || red "demo governance files missing"

# ── Reset demo state ──────────────────────────────────────────────────
header "2. Reset Demo State"

rm -rf governance/agents/apex-loan-processor 2>/dev/null
rm -rf governance/agents/demo-new-agent 2>/dev/null
green "Cleared previous demo agents"

# Keep pre-built demo agents
[[ -d "demo/governance/agents/demo-payment-agent" ]] \
  && green "Pre-built demo agents intact" \
  || red "Pre-built demo agents missing"

# ── Step 0: iris explain ──────────────────────────────────────────────
header "3. Demo Step 0: iris explain (Trust)"

OUTPUT=$(iris explain 2>&1)
[[ $? -eq 0 ]] && green "iris explain runs cleanly" || red "iris explain failed: $OUTPUT"
echo "$OUTPUT" | grep -q "NEVER blocks" && green "Key message present: NEVER blocks in dev" || yellow "Check iris explain output"

# ── Step 1: iris status ───────────────────────────────────────────────
header "4. Demo Step 1: iris status (Dashboard)"

OUTPUT=$(iris status 2>&1)
[[ $? -eq 0 ]] && green "iris status runs cleanly" || red "iris status failed"
echo "$OUTPUT" | grep -q "PROD READY" && green "At least one PROD READY agent showing" || yellow "No PROD READY agents — check demo governance files"
echo "$OUTPUT" | grep -q "demo-payment-agent" && green "demo-payment-agent visible in status" || red "demo-payment-agent missing from status"

# ── Step 2: iris scan --discover ──────────────────────────────────────
header "5. Demo Step 2: iris scan --discover (Brownfield)"

[[ -d "demo/customers/meridian_health" ]] || { red "demo/customers/meridian_health missing"; }

OUTPUT=$(iris scan --dir demo/customers/meridian_health --discover 2>&1 </dev/null)
[[ $? -eq 0 || $? -eq 1 ]] && green "iris scan --discover runs" || red "iris scan --discover crashed"
echo "$OUTPUT" | grep -qi "ungoverned\|finding\|detected\|FAIL\|anthropic\|openai\|langchain" \
  && green "Findings detected in demo customer files" \
  || yellow "No findings detected — verify demo customer agent files exist"

# ── Step 3: iris register ─────────────────────────────────────────────
header "6. Demo Step 3: iris register (Greenfield)"

OUTPUT=$(iris register \
  --name apex-loan-processor \
  --owner platform@apexcapital.com \
  --team ai-platform \
  --compliance colorado-ai-act \
  --high-risk 2>&1)
[[ $? -eq 0 ]] && green "iris register works" || red "iris register failed: $OUTPUT"
[[ -f "governance/agents/apex-loan-processor/passport.yaml" ]] \
  && green "passport.yaml created" \
  || red "passport.yaml not created"
[[ -f "governance/agents/apex-loan-processor/policy-intent.md" ]] \
  && green "policy-intent.md created" \
  || red "policy-intent.md not created"

# ── Step 4: iris framework suggest ───────────────────────────────────
header "7. Demo Step 4: iris framework suggest (Advisor)"

OUTPUT=$(echo "" | iris framework suggest --agent apex-loan-processor 2>&1 || true)
[[ -n "$OUTPUT" ]] && green "iris framework suggest produces output" || red "iris framework suggest produced no output"
echo "$OUTPUT" | grep -qi "colorado\|action\|recommend\|framework\|required" \
  && green "Framework recommendations present" \
  || yellow "Check iris framework suggest output"

# ── Step 5: iris compliance check FAIL ───────────────────────────────
header "8. Demo Step 5: Compliance FAIL (Expected)"

OUTPUT=$(iris compliance check --framework colorado-ai-act 2>&1 </dev/null || true)
echo "$OUTPUT" | grep -qi "FAIL\|violation\|CO-00" \
  && green "Compliance check correctly shows violations for new agent" \
  || yellow "Expected violations not showing — demo may be less dramatic"

# ── Step 6: iris drift ────────────────────────────────────────────────
header "9. Demo Step 6: iris drift (Continuous Governance)"

OUTPUT=$(iris drift snapshot 2>&1)
[[ $? -eq 0 ]] && green "iris drift snapshot works" || red "iris drift snapshot failed: $OUTPUT"

OUTPUT=$(iris drift check 2>&1 </dev/null || true)
[[ $? -le 1 ]] && green "iris drift check runs" || red "iris drift check crashed"

# ── Step 7: iris watch ────────────────────────────────────────────────
header "10. Demo Step 7: iris watch (Live Decisions)"

timeout 2 iris watch --agent demo-payment-agent 2>&1 | head -3 > /tmp/iris_watch.txt || true
[[ -s /tmp/iris_watch.txt ]] && green "iris watch starts up" || yellow "iris watch: no output (vault may be empty — run a test call first)"

# ── Step 8: iris compliance check PASS ───────────────────────────────
header "11. Demo Step 8: Compliance PASS (Pre-built agent)"

OUTPUT=$(iris compliance check --framework colorado-ai-act --dir demo/governance 2>&1 </dev/null || true)
echo "$OUTPUT" | grep -qi "PASS\|satisfied" \
  && green "demo-payment-agent shows PASS" \
  || red "demo-payment-agent not passing — check demo/governance passport.yaml"

# ── Step 9: iris evidence report ─────────────────────────────────────
header "12. Demo Step 9: iris evidence report (Audit Trail)"

OUTPUT=$(iris evidence report --agent demo-payment-agent --dir demo/governance 2>&1 || true)
[[ -n "$OUTPUT" ]] && green "iris evidence report produces output" || yellow "iris evidence report: no output"

# ── Step 10: iris red-team ─────────────────────────────────────────────
header "13. Demo Step 10: iris red-team (Pro Preview)"

OUTPUT=$(iris red-team --agent demo-payment-agent --dir demo/governance 2>&1 || true)
[[ -n "$OUTPUT" ]] && green "iris red-team runs and produces output" || yellow "iris red-team: no output"
echo "$OUTPUT" | grep -qi "risk\|test\|bypass\|pro" \
  && green "Red team output looks correct" \
  || yellow "Check iris red-team output format"

# ── Visual setup check ────────────────────────────────────────────────
header "14. Pre-Call Visual Checklist"

echo "  Before your call, manually verify:"
echo ""
echo "  □ Terminal font is 16pt or larger"
echo "  □ Terminal background is dark (black)"
echo "  □ Dock is hidden (Cmd+Option+D)"
echo "  □ Pitch deck is open in a second window"
echo "  □ IRIS_Pitch_Deck_v2.pptx is the correct version"
echo "  □ Second terminal tab is open for iris watch"
echo "  □ demo/README.md is open for the speaking script"
echo ""

# ── Summary ───────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════╗"
printf "  ║  Results: \033[32m%2d passed\033[0m  \033[33m%2d warnings\033[0m  \033[31m%2d failed\033[0m     ║\n" $PASS $WARN $FAIL
echo "  ╚══════════════════════════════════════════════╝"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo -e "\033[31m  ✗ $FAIL check(s) failed. Fix before the call.\033[0m"
  echo ""
  exit 1
elif [ "$WARN" -gt 0 ]; then
  echo -e "\033[33m  ⚠ $WARN warning(s). Review above but demo can proceed.\033[0m"
  echo ""
  exit 0
else
  echo -e "\033[32m  ✓ All checks passed. You are ready to demo.\033[0m"
  echo ""
  echo "  Run the full demo with:"
  echo "  PAUSE=true bash demo/run_demo.sh"
  echo ""
  exit 0
fi
