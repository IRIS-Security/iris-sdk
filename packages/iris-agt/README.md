# IRIS AGT

Compliance intelligence from [Microsoft AGT](https://github.com/microsoft/agent-governance-toolkit)
(agent-governance-toolkit) audit trails. Keep your AGT policy enforcement,
zero-trust identity, and sandboxing. IRIS reads AGT's own audit-trail export
and tells you which regulations apply — with tamper-evident proof.

AGT's own compliance docs are explicit that its framework mappings (EU AI
Act, NIST AI RMF, SOC 2, ISO 42001) are self-assessments, not a conformity
assessment or legal advice — AGT's EU AI Act checklist puts it directly:
*"Organizations should engage qualified legal counsel and notified bodies
for formal compliance evaluation."* AGT also doesn't map GDPR, HIPAA, or
Colorado's SB 26-189 at all. That's the gap this adapter closes: it reads
what AGT already recorded and runs it through IRIS's regulatory registry.

## Install

```bash
pip install iris-agt
```

## Quickstart

AGT runs in-process with the agents it governs — there's no remote API to
query. This adapter reads whatever AGT already exported to disk: a
`FileAuditSink` JSON-Lines trail, or a `CloudEvents`/`audit.export()` JSON
document.

```bash
iris compliance scan --from agt --audit-file audit_trail.jsonl
```

Or from Python:

```python
from iris_agt import profile_from_agt

profile = profile_from_agt("audit_trail.jsonl")
```

## Profile data IRIS derives

Agent count (distinct `agent_did` values), autonomy level (tool-invocation
frequency and `rogue_detection`/`quarantine` signals), data-category hints
(keyword scan over `resource`/`policy_decision`/`matched_rule` text only).
AGT's `AuditEntry` schema carries no model, provider, or orchestration-
framework field, so those three signals are left empty rather than guessed.

**Privacy:** IRIS reads audit-entry *structure* only — `entry_id`,
`timestamp`, `event_type`, `agent_did`, `action`, `resource`, `outcome`,
`policy_decision`, `matched_rule`, hash-chain fields, `trace_id`,
`session_id`. The `data` field (tool call arguments and other free-form
payload content) is never read.

**Chain integrity:** by default, `profile_from_agt` checks that each
entry's `previous_hash` matches the prior entry's `entry_hash` and raises
if the chain is broken. This is a structural continuity check over the
exported subset, not an independent cryptographic re-derivation of AGT's
SHA-256 hashes. Pass `verify_chain=False` to skip it (e.g. for a
deliberately filtered/partial export).

## Push to IRIS Cloud (optional)

```bash
iris compliance scan --from agt --audit-file audit_trail.jsonl --push
```

Requires `IRIS_API_KEY`. Pushing a one-time snapshot is free; continuous
posture tracking and evidence mapping over time are IRIS Cloud features.

## License

Apache 2.0.
