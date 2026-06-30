# Model Governance Guide

Govern **which LLM models** your agents may call — not just which APIs. IRIS model
governance addresses frontier-model risk, export-control restrictions, and emergency
provider or government directives (e.g. sudden suspension of cyber-capable models).

**Runs fully local.** No hosted API required. Optional Enterprise control plane
can push directive updates org-wide later; evaluation logic stays in-process.

---

## When to use this

| Scenario | IRIS control |
|----------|--------------|
| Agent uses standard models only | Default registry; no extra config |
| Agent uses frontier / cyber-capable models | Tier + export-control + HITL gates |
| Government or provider suspends a model | Directive kill switch + auto-fallback |
| Security team needs audit trail | Evidence Vault records blocks and fallbacks |

---

## Architecture

```
governance/
  models/
    registry.yaml       ← model tiers, export control, fallbacks
  directives/
    active.yaml         ← emergency suspensions (hot-reload)
  agents/
    my-agent/
      passport.yaml     ← allowed_model_tiers, allowed_models
```

At inference time:

1. SDK loads registry + directives (hot-reload on each call)
2. If model is suspended → auto-fallback (if configured) or block
3. If model tier is `frontier-restricted` → check work authorization + HITL
4. Passport allowlists are enforced
5. Event logged to Evidence Vault

---

## Model Capability Registry

Edit `governance/models/registry.yaml`:

```yaml
apiVersion: iris.io/v1alpha1
kind: ModelRegistry
metadata:
  name: default
spec:
  models:
    claude-sonnet-4-6:
      provider: anthropic
      tier: standard
      export_control: unrestricted

    claude-fable-5:
      provider: anthropic
      tier: frontier-restricted
      capabilities: [cyber-analysis, code-audit]
      export_control: bis-restricted
      retention_days: 30
      requires_hitl: true
      allowed_work_authorizations:
        - us-citizen
        - us-permanent-resident
      fallback_model: claude-sonnet-4-6
      aliases:
        - claude-fable-*
```

### Model tiers

| Tier | Meaning |
|------|---------|
| `standard` | General-purpose models, no extra gates |
| `frontier` | Enhanced capability; fallback recommended |
| `frontier-restricted` | Export-control or national-security sensitivity |

### Export control values

| Value | Meaning |
|-------|---------|
| `unrestricted` | No nationality gate |
| `bis-restricted` | BIS / export-control rules apply |
| `government-suspended` | Provider or government recall (use directives) |

IRIS ships a bundled default registry when no `governance/models/registry.yaml`
exists in your repo.

---

## Directive kill switches

When a model must be suspended org-wide, edit `governance/directives/active.yaml`
and merge via PR:

```yaml
apiVersion: iris.io/v1alpha1
kind: DirectiveRegistry
metadata:
  name: active
spec:
  directives:
    - directive_id: bis-2026-0612-fable
      model_id: claude-fable-5
      status: suspended
      effective_at: "2026-06-12T21:21:00Z"
      reason: US government export control directive
      source: regulatory
      fallback_model: claude-sonnet-4-6
```

IRIS hot-reloads directives on the next inference call. No application redeploy.

```bash
iris models directives    # show active suspensions
iris models reload        # verify files load
```

To lift a suspension, remove or set `status: lifted` and merge.

---

## Agent passport

Declare which models an agent may use:

```yaml
# governance/agents/security-audit-agent/passport.yaml
spec:
  allowed_model_tiers:
    - standard
    - frontier-restricted
  allowed_models:
    - claude-sonnet-4-6
    - claude-fable-5
```

If `allowed_model_tiers` or `allowed_models` are set, calls outside the allowlist
are blocked.

---

## SDK integration (Anthropic)

```python
from iris_anthropic import IrisAnthropic

client = IrisAnthropic(
    passport=passport,
    user_work_authorization="us-citizen",  # or IRIS_USER_WORK_AUTHORIZATION
    auto_fallback=True,                    # default — reroute on suspension
    hitl_approved=False,                   # True after security review
)

response = client.messages.create(
    model="claude-fable-5",
    max_tokens=4096,
    messages=[{"role": "user", "content": "Audit this codebase for vulnerabilities."}],
)
```

When `claude-fable-5` is suspended and `auto_fallback=True`, IRIS routes to
`claude-sonnet-4-6` and logs the event.

### Environment variables

| Variable | Purpose |
|----------|---------|
| `IRIS_USER_WORK_AUTHORIZATION` | Export-control check (`us-citizen`, `us-permanent-resident`) |
| `IRIS_ENV` | `dev` warns; `production` blocks |

---

## CLI reference

```bash
iris models list                  # all models in registry
iris models list --tier frontier-restricted
iris models list --format json
iris models directives            # active kill switches
iris models reload                # validate YAML loads
iris explain                      # what IRIS does at inference time
```

---

## Policy rules

| Rule ID | Severity | Trigger |
|---------|----------|---------|
| `IRIS-MODEL-001` | CRITICAL | Active suspension directive (no fallback applied) |
| `IRIS-MODEL-002` | HIGH | Model not in passport `allowed_models` |
| `IRIS-MODEL-003` | HIGH | Model tier not in passport `allowed_model_tiers` |
| `IRIS-MODEL-004` | CRITICAL | Export-control: invalid work authorization |
| `IRIS-MODEL-005` | HIGH | Frontier model requires HITL in staging/production |

Run `iris explain` for the full inference flow. In Cursor, MCP surfaces these
rule IDs with suggested fixes.

---

## GitOps workflow

1. Security team updates `governance/directives/active.yaml` (or registry)
2. PR reviewed and merged
3. CI runs `iris models reload` and `iris scan`
4. All agents with `IrisAnthropic` pick up changes on next call
5. Evidence Vault records blocks, fallbacks, and violations

---

## SDK vs hosted control plane

| Capability | SDK (now) | Hosted (Enterprise, planned) |
|------------|-----------|------------------------------|
| Model registry | `governance/models/registry.yaml` | Central registry API + sync |
| Directives | `governance/directives/active.yaml` | Push to all agents in minutes |
| Evaluation | In-process Cedar | Same engine, cached config |
| Audit | Local Evidence Vault | Vault sync to control plane |
| Cost | $0 infra | Team / Enterprise tier |

The SDK is sufficient for most teams. Hosted adds value when you need sub-minute
org-wide directive propagation across hundreds of agents and regions.

---

## Example: Fable / Mythos-style incident

1. Government directive suspends `claude-fable-5` for foreign nationals
2. Security adds directive to `governance/directives/active.yaml`
3. `iris models directives` confirms suspension
4. Agents with `auto_fallback=True` route to `claude-sonnet-4-6`
5. Agents without fallback fail closed in production
6. Evidence Vault provides audit trail for appeals or internal review

---

## Related docs

- [README](../README.md#model-governance-frontier-models-and-export-control)
- [QUICKSTART](../QUICKSTART.md)
- [iris-anthropic README](../packages/iris-anthropic/README.md)
- [RELEASE.md](../RELEASE.md)
