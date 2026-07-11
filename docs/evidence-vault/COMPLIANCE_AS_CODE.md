# Compliance as Code, Evidence as Code

These are not two new features. They are names for two properties
IRIS's architecture already has by construction:

## Compliance as Code
governance/agents/<name>/policy.cedar IS the compliance policy,
version-controlled, PR-reviewed, diffable (iris preview). This
was built in the Policy as Code work — this section just names
it for the auditor-facing documentation package.

## Evidence as Code
The CI/CD integrations in this prompt mean every pipeline run —
every PR, every terraform apply, every ArgoCD sync — writes a
permanent, queryable EvidenceEvent. The evidence trail is not a
log file that rotates out or a dashboard snapshot; it is data
with the same durability and queryability guarantees as the code
that produced it. "Evidence as Code" means: if you can ask
"what changed in this PR," you can ask "what evidence did this
PR generate," using the same mental model and almost the same
tooling (iris evidence record-cicd is a CLI command, same as
any other CI step).

Together: Compliance as Code declares what SHOULD happen.
Evidence as Code proves what DID happen. The gap between those
two — declared policy vs actual enforcement — is exactly what
iris drift check and iris sentinel monitor continuously.
