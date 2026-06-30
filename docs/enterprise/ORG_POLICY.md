# IRIS Enterprise — Organizational Security Policy

## The hybrid model

IRIS uses a two-file model:

1. **Org baseline** (your security repo): `iris-security.yaml` — security team owns entirely
2. **Project override** (each agent repo): `.iris-security` — inherits from org baseline, adds restrictions only

Developers can add restrictions. They cannot remove org baseline rules.

## Quick start

### Step 1: Security team creates the security repo

Use the template at `templates/security-repo/`. Set `IRIS_SECURITY_POLICY_URL` in your GitHub org variables.

```bash
iris org-policy init --type org > iris-security.yaml
iris org-policy validate --file iris-security.yaml
```

### Step 2: Developers reference it automatically

No developer action needed. IRIS reads `IRIS_SECURITY_POLICY_URL` from the environment and fetches the org baseline on every run.

### Step 3: Projects add restrictions as needed

Create `.iris-security` in the agent repo with `extends:` pointing to the org baseline.

```bash
iris org-policy init --type project > .iris-security
iris org-policy validate
```

## Environment setup guide

| Team | Action |
|---|---|
| Security team | Create security repo from template |
| Security team | Define environments in `iris-security.yaml` |
| Platform team | Set `IRIS_SECURITY_POLICY_URL` as org variable |
| DevOps team | Set `IRIS_ENV` in deployment configs per environment |
| Developers | Create `.iris-security` only if project needs more restrictions |

## How enforcement levels work

| Rule fires | OFF | OBSERVE | WARN | ENFORCE |
|---|---|---|---|---|
| BLOCK tier | nothing | log only | terminal warning | raise error / block call |
| HITL tier | nothing | log only | terminal warning | pause call / notify human |
| INFORM tier | nothing | log only | log only | log only |

### Absolute blocks

Five rules always block regardless of environment or enforcement level:

- MH-001
- CHAT-004
- HIPAA-003
- PIPL-001
- GDPR-005

No configuration can disable these.

## Kubernetes deployment

Set the environment via pod env var:

```yaml
env:
  - name: IRIS_ENV
    value: production-eu
```

Or namespace label (with K8s sidecar):

```yaml
metadata:
  labels:
    iris.io/environment: production-eu
```

## CLI reference

```bash
iris org-policy init [--type org|project]
iris org-policy validate [--env <environment>]
iris org-policy show --env production
iris org-policy diff [--base main]
iris org-policy cache [--clear] [--refresh]
iris org-policy audit [--days 90]
```
