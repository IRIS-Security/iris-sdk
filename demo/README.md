# IRIS SE Demo Guide

Complete Sales Engineer demo environment for proving every free-tier IRIS
feature works end to end. Run this before investor calls and design partner meetings.

## Before every demo

1. Run: `python3 demo/scripts/verify_demo.py`
2. Set your font to 16pt in the terminal
3. Set `PAUSE=true` so you can speak between steps
4. Have the pitch deck open in a second window

## Quick start

```bash
bash demo/setup.sh
PAUSE=false bash demo/run_demo.sh   # automated dry run
PAUSE=true bash demo/run_demo.sh    # live demo with pauses
```

## The demo story (say this out loud)

**STEP 0 — Brownfield discovery arc**
→ `iris scan --dir demo/customers/meridian_health --discover`
→ `iris scan --dir demo/customers/meridian_health --discover --govern --no-auto-apply`

IRIS found ungoverned agents and showed the exact one-line change for each file.

**STEP 1 — Build trust before changing anything**
→ `iris explain`

**STEP 2 — Register and get an action plan (not a checklist)**
→ `iris register --name apex-loan-processor ...`
→ `iris framework suggest --agent apex-loan-processor`

**STEP 3 — Status check (like git status for compliance)**
→ `iris status`

**STEP 4 — Follow the action plan**
→ `iris compliance assess --agent apex-loan-processor`
→ `iris compliance check --framework colorado-ai-act`

**STEP 5 — Watch decisions in real time**
→ Second terminal: `iris watch --agent demo-payment-agent`

**STEP 6 — Score moved up**
→ `iris status` again

**STEP 7 — Audit trail**
→ `iris evidence report --agent demo-payment-agent --dir demo/governance/agents`

## How to handle the trust question

When a developer or SRE says: *"I am not comfortable adding a dependency
to my production agent code"*

Say this:

*"Completely fair. Let me show you exactly what it does."*
→ Run: `iris explain`

*"It proxies every single attribute identically. Your existing tests
will pass. In dev mode it cannot block anything. And you can watch every
decision it makes in real time."*
→ Open a second terminal: `iris watch --agent <name>`
→ In the first terminal: run your agent once

*"You just saw every decision IRIS made. Nothing was blocked.
Everything was logged. That log is your audit trail."*

That sequence converts a skeptical SRE in under three minutes.

## Demo customers

| Customer | Type | Domain |
|---|---|---|
| `customers/apex_capital/` | Greenfield | Financial services / lending |
| `customers/meridian_health/` | Brownfield | Healthcare / PHI |

## Pre-built governance

| Agent | Status | Purpose |
|---|---|---|
| `governance/agents/demo-payment-agent/` | PASS | Fully compliant financial agent |
| `governance/agents/demo-hr-agent/` | PASS | Fully compliant employment agent |

## Reset between demos

```bash
bash demo/reset.sh
```
