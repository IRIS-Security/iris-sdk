# IRIS Org Discovery — Least-Privilege Access Requirements

Granting IRIS read-only access to your organization's AI estate should take a
5-minute security review, not a week-long procurement cycle. These templates
grant the minimum permissions required for org-wide agent discovery.

## SCM (GitHub / GitLab / Bitbucket / Azure DevOps)

**Required scope:** read repository contents only — no write, no admin.

### GitHub — fine-grained PAT (recommended)

Create a fine-grained personal access token with:

| Permission | Access |
|---|---|
| Repository access | Selected repositories OR all repos in org |
| Contents | Read-only |
| Metadata | Read-only |

Do **not** grant the broad classic `repo` scope. IRIS only needs to list org
repos and read file contents on the default branch.

### GitHub App installation (enterprise)

```yaml
permissions:
  contents: read
  metadata: read
```

### GitLab

Project/group token with `read_repository` scope only.

### Bitbucket / Azure DevOps

Read-only token scoped to `Code (Read)` / `Contents (Read)`.

---

## Kubernetes

IRIS discovers agents in **running workloads** using read-only cluster RBAC.
It never reads secret **values** — only secret **names** (via list/watch).

Apply the ClusterRole template:

```bash
kubectl apply -f docs/discovery/k8s-discovery-clusterrole.yaml
```

Then bind to your IRIS service account:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: iris-discovery
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: iris-discovery-reader
subjects:
  - kind: ServiceAccount
    name: iris-discovery
    namespace: iris-system
```

### Explicit exclusions

- `secrets` **get** is NOT granted (would expose secret values)
- `secrets` list/watch IS granted (names only, for signal detection)
- No create/update/patch/delete on any resource

---

## CI/CD

Read-only API tokens scoped to pipeline **definition** reads:

| Platform | Scope |
|---|---|
| GitHub Actions | `actions:read` (workflow file access via contents:read) |
| GitLab CI | `read_api` + `read_repository` |
| Jenkins | Read-only API token |
| CircleCI | `view-builds` + project read |

Pipeline execution logs are not required for v1 discovery.

---

## MCP Registry

Not yet implemented. When enabled, IRIS will require read-only access to your
MCP registry endpoint or config files (`mcp.json`, `claude_desktop_config.json`).

---

## Environment variables (CLI)

```bash
export GITHUB_TOKEN=ghp_...          # fine-grained PAT, contents:read
export KUBECONFIG=/path/to/kubeconfig
export IRIS_DISCOVERY_CONFIG=/path/to/discovery.json  # optional
```

See `iris discover org --help` for interactive onboarding on first run.
