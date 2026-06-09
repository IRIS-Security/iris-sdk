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

**"Let me show you what IRIS does to an existing codebase first."**
→ `iris scan --dir demo/customers --discover`

See those findings? Those are real agent files with no governance.
IRIS found them automatically. In your org, it would scan every
repository and show you every ungoverned agent your team has built.

**"Now let me register a new one from scratch."**
→ `iris register --name apex-loan-processor ...`

**"IRIS immediately tells me which regulations apply."**
→ `iris framework suggest --agent apex-loan-processor`

**"Watch what happens when I check compliance on a new agent."**
→ `iris compliance check` (it fails — this is the hook)

**"Now I run the impact assessment. Eight questions. Takes two minutes."**
→ `iris compliance assess --agent apex-loan-processor`

**"Here is an agent that has already been through this process."**
→ Show `demo-payment-agent` compliance check — PASS

**"And here is the full audit trail IRIS generates."**
→ `iris evidence report --agent demo-payment-agent --dir demo/governance/agents`

**"And Cursor caught it in the IDE before it ever ran."**
→ Show Cursor MCP integration screenshot

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
