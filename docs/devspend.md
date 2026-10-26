# `iris devspend` — developer tool spend tracking

**Status: Phase 1 — Claude Code adapter only.** Cursor and OpenAI coding
tools are planned as additional log-source adapters; they are not
available yet. Everything below applies to Claude Code sessions.

## What this is (and isn't)

`iris devspend` tracks what it costs *you, the developer* to use an AI
coding assistant to build a project — parsed from that tool's local
session logs on your machine.

This is a different thing from `iris cost`, which tracks spend from
agents IRIS governs at runtime through its instrumented SDK adapters
(production LLM call cost). The two commands don't share a namespace,
a package, a CLI group, or a storage location, and they never will —
`iris devspend` is about the cost of building software with an AI
assistant; `iris cost` is about the cost of running the software you
built. If you're looking for production agent spend, see `iris cost`
instead.

## Install / requirements

No setup beyond having Claude Code installed and having used it in this
project — `iris devspend` reads Claude Code's own local session
transcripts (`~/.claude/projects/<project>/*.jsonl`). Nothing is sent
anywhere: parsing, pricing, and storage are all local.

## `iris devspend report`

One-shot rollup for the current project: total tokens, total estimated
spend, a breakdown by model, a breakdown by tool source (currently
always `claude-code`), and any heuristic inefficiency flags detected.

```bash
iris devspend report
iris devspend report --format json
```

Sample output:

```
iris devspend report — /path/to/your/project

Sessions:     9
Total tokens: 2,148,056,154
Total spend:  $890.78

       Spend by model
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Model           ┃    Cost ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ claude-sonnet-5 │ $890.78 │
└─────────────────┴─────────┘

By tool
  claude-code: $890.78

Heuristic flags (informational — human judgment required)
  ⚠ oversized_system_prompt: 9
Run with --format json for per-flag detail.
```

Every run re-parses whatever Claude Code session logs exist for the
current project and refreshes `.iris/devspend/<session_id>.json` — one
file per session, project-local (see Storage below).

## `iris devspend live`

An ambient chip: a single line that redraws in place, showing running
totals for the current project. Non-blocking — it re-parses at most one
session file per refresh tick (whichever was modified most recently),
not the full project history, so it stays cheap even in long sessions
with large transcripts.

```bash
iris devspend live
iris devspend live --interval 5   # seconds between refreshes, default 2
```

Color is muted (dim) during normal operation. Red is reserved
exclusively for the flag/warning state — a large but unflagged spend
number stays muted; red only appears when a heuristic below is
currently flagging something. Ctrl+C stops it cleanly.

## Heuristic inefficiency flags

Flag-only in this phase — these surface something worth a look, they
don't suggest a fix. (Concrete fix suggestions are planned as a paid
capability, later.)

Devspend deliberately never stores your actual prompts, code, or model
responses — only token counts, model names, and structural markers
(like a compaction event). That's a data-minimization choice: your
session transcripts are the most sensitive thing on your machine from a
"what did I just paste into an AI tool" standpoint, and devspend has no
need to see any of it to report spend. One consequence: the flags below
are approximated from token-count *shapes*, not from actually comparing
what was in your prompts. Each one says so in its own detail message.

- **`context_reload`** — Claude Code's context-compaction boundary was
  followed by a large fresh cache write (≥80% the size of the context
  held before compaction). Read as: the same large context block was
  probably rebuilt from scratch rather than served from cache.
- **`oversized_system_prompt`** — a session's first cache write (system
  prompt + tool schemas, typically) was more than 20% of that turn's
  total input tokens. This is a size proxy, not a judgment about
  whether the task actually warranted it — that call is left to you.
- **`no_caching_detected`** — five or more turns in a session show
  repeated cache writes (shared context worth caching) but zero cache
  reads the whole session. Caching doesn't appear to be taking effect.

## Storage

`.iris/devspend/<session_id>.json`, one file per session, rooted at the
project directory (git top-level, or the current directory if not a git
repo) — project-local, the same way `.git/` is, not under your home
directory. This is gitignored by default; it's a local cache, not
something to commit.

```json
{
  "schema_version": 1,
  "session_id": "...",
  "tool_source": "claude-code",
  "started_at": "2026-08-01T10:00:00.000Z",
  "ended_at": "2026-08-01T10:10:00.000Z",
  "turns": [
    {
      "turn_id": 1,
      "input_tokens": 100,
      "output_tokens": 300,
      "cache_creation_tokens": 8000,
      "cache_read_tokens": 0,
      "model": "claude-sonnet-5",
      "estimated_cost_usd": 30.45
    }
  ],
  "flags": [
    {
      "type": "oversized_system_prompt",
      "turn_id": 1,
      "detail": "..."
    }
  ],
  "total_tokens": 8400,
  "total_cost_usd": 30.45
}
```

## Pricing

Sourced from the same pricing registry `iris cost` uses
(`iris_core.cost.pricing.PricingRegistry`) — one table, not a duplicate.
Custom or newer model pricing can be added via
`~/.iris/pricing-overrides.yaml`, same as `iris cost pricing --update`
documents. Unknown models price at $0.00 with a logged warning rather
than guessing.

## Coming next

- **Cursor** — a second local-log adapter, same schema and CLI.
- **OpenAI coding tools** — a third adapter for OpenAI's coding-assistant
  products specifically (unrelated to the existing `iris-openai`
  governed-agent SDK adapter used by `iris cost`).
- Enterprise/paid, later: cross-project and cross-tool devspend trends
  over time, cost projection (burn rate + completion velocity), and
  concrete prompt-efficiency fix suggestions built on top of the flags
  above.
