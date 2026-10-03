# IRIS Backlog — Business and Enterprise Capabilities

Every capability below has a written architecture spec
(linked). NONE are enabled for any customer yet. A capability
only moves to "Shippable" when it has passing tests in CI
against real, running code — never on spec completeness alone.

Status legend:

- Backlog — spec exists, no code written
- In progress — code exists, tests not all passing
- Shippable — tests passing in CI, not yet sold to a customer
- Live — enabled for real customers

## Ordering principle: closest to revenue first

This backlog is ordered by which capability removes the biggest
blocker for an actual deal soonest — NOT by dependency
convenience, and not by build difficulty. Two tracks run in
PARALLEL, not sequentially, because they unblock two different
buyer motions:

Track A — self-serve Business, no new frontend required. Every
capability in Track A is CLI-driven and the terminal already
renders it; these can become Shippable without IRIS Cloud
Console existing at all. This is the fastest path to any
revenue and should be worked first in raw priority order.

Track B — Enterprise, gated on IRIS Cloud Console. SSO is the
named, specific, recurring blocker for the first enterprise
contract — industry data puts that threshold at the $30-50k
deal size — but SSO cannot ship before the Console exists in
even minimal (auth-shell-only) form. Track B's first row is
therefore the Console MVP itself, not SSO directly.

Work both tracks concurrently: Track A funds the company and
builds the AIUC-1/Schellman and Employ-style design-partner
credibility while Track B's longer lead time (a net-new web
app) is in progress.

## Blocking dependency: IRIS Cloud Console (Track B only)

Track B capabilities below require a web application that does
not exist yet — see [docs/architecture/FRONTEND_SURFACE_MAP.md](docs/architecture/FRONTEND_SURFACE_MAP.md).
Track A requires no new frontend and is not blocked by this.

### Track A — promote in this order (revenue-closest, no Console needed)

| Rank | Capability | Status | Spec | Why this rank |
|---|---|---|---|---|
| A1 | compliance_full_eval | Shippable | [CURSOR bundles](docs/specs/CURSOR_CCPA_PIPL.md), [employment AI](docs/specs/CURSOR_EMPLOYMENT_AI_BUNDLES.md), [AIUC-1 / ISO 42001](docs/specs/CURSOR_AIUC1_ISO42001.md) | The actual reason anyone pays — "see the gap free, prove the fix paid." Unlocks every other Business conversation. |
| A2 | certify_export | Shippable | [CURSOR AIUC-1 Part 2](docs/specs/CURSOR_AIUC1_ISO42001_PART2.md) | A1 with no export is a teaser, not a product — this is what actually gets handed to an auditor or to Schellman. |
| A3 | audit_log_export | Shippable | [CURSOR three-tier pricing Part 3](docs/specs/CURSOR_THREE_TIER_PRICING_PART3.md) | CLI-only, fast to build, directly answers a security-questionnaire line item without waiting on the Console. |
| A4 | hitl_notifications | Shippable | [CURSOR HITL Part 3](docs/specs/CURSOR_HITL_PART3.md) | Converts HITL from something a developer checks via CLI into a daily habit a whole team depends on — the strongest day-to-day stickiness lever in Business. |
| A5 | github_app_org | In progress | [CURSOR GitHub App](docs/specs/CURSOR_GITHUB_APP_DYNAMIC_PYPI.md) | Expands the GitHub adoption motion from individual repos to whole orgs — a natural upsell once A1-A4 prove value. |
| A6 | mcp_pro_tools | In progress | [CURSOR MCP Server](docs/specs/CURSOR_MCP_SERVER.md) | Depends on A1 + A4 being real; sequenced after them deliberately. |
| A7 | vault_siem_export | Shippable | [CURSOR enterprise security Part 4](docs/specs/CURSOR_ENTERPRISE_SECURITY_PART4.md) | Real demand, but no specific deal is currently blocked on it — lowest priority within Track A. |
| A8 | evidence_vault_cloud | Backlog | [CURSOR Evidence Vault v2](docs/specs/CURSOR_EVIDENCE_VAULT_V2.md) | Valuable, but its full value (a dashboard view) needs the Console — partial CLI-only version can ship here, full version waits for Track B. |

### Track B — promote in this order (Enterprise, Console-gated)

| Rank | Capability | Status | Spec | Why this rank |
|---|---|---|---|---|
| B1a | iris-cloud-console-api | Live | [CURSOR Console Migration Part 3](docs/specs/CURSOR_CONSOLE_MIGRATION_PART3.md) | FastAPI backend serving real org data — identities, policies, evidence, integrations. Design-partner ready. |
| B1b | iris-cloud-console frontend | Live | [CURSOR Console Migration Parts 1-2, 4-6](docs/specs/CURSOR_CONSOLE_MIGRATION_PARTS1-6.md) | React SPA wired to B1a — 60+ pages, light/dark theme, IRIS design tokens. Base44 stripped. |
| B2 | sso_saml_oidc | In progress | [CURSOR three-tier pricing Part 4](docs/specs/CURSOR_THREE_TIER_PRICING_PART4.md) | The specific, named, recurring blocker on the first $30-50k+ enterprise contract. Highest-leverage single capability in Track B. |
| B3 | org_policy_enforcement | Backlog | [CURSOR hybrid org policy](docs/specs/CURSOR_HYBRID_ORG_POLICY.md) | This is the actual Enterprise product thesis (org-wide governance authority) — the thing that justifies Enterprise pricing over Business, not just an access-control feature. |
| B4 | enterprise_vault_integrations | Backlog | [CURSOR GHA vault Bedrock](docs/specs/CURSOR_GHA_VAULT_BEDROCK.md) | Common diligence question for regulated-industry prospects (financial services, healthcare) — pairs naturally with B3 conversations. |
| B5 | rbac_custom_roles | Shippable | [CURSOR three-tier pricing Part 5](docs/specs/CURSOR_THREE_TIER_PRICING_PART5.md) | Custom roles + scope resolver ship in iris-core; gate stays per-capability until a signed deal needs org rollout. |
| B6 | fedramp_region_enforcement | Backlog | [CURSOR enterprise security](docs/specs/CURSOR_ENTERPRISE_SECURITY.md) | Targets a specific, narrower buyer (government/regulated) — promote only once that conversation is live. |
| B7 | byok_encryption | Backlog | [CURSOR three-tier pricing Part 6](docs/specs/CURSOR_THREE_TIER_PRICING_PART6.md) | Depends on B4; real but no current deal is blocked on it specifically. |
| B8 | scim_provisioning | Backlog | [CURSOR three-tier pricing Part 5 (scaffold)](docs/specs/CURSOR_THREE_TIER_PRICING_PART5_SCIM.md) | Build only when an actual signed customer asks — per the research finding that SCIM has high effort and near-zero payoff until that exact moment. |

## Promotion process

1. Pick the lowest-ranked unstarted row in whichever track has
   capacity (both tracks can run in parallel with different
   people/sessions). Run its linked Cursor prompt.
2. Write the tests already specified in that prompt's Part labeled "Tests".
3. Get them passing in CI — not just locally.
4. Open a PR that updates this table's status AND flips the
   corresponding entry in CAPABILITY_FLAGS from BACKLOG to
   SHIPPABLE in the same commit. The two must move together —
   never update one without the other.
5. SHIPPABLE means available to enable for a design partner, not
   automatically sold. A human decision (not a flag) moves
   SHIPPABLE to LIVE the first time a real customer needs it.
6. Re-rank if reality changes the picture — if a specific named
   Enterprise prospect asks for, say, FedRAMP region enforcement
   (B6) before SSO is done, that conversation is the new ranking
   signal and this table should be edited to reflect it. The ranks
   above are the best ordering with the information available now,
   not a fixed roadmap.

## Free-tier framework expansion (adoption lever, not a capability build)

Free assessment across every framework moves adoption; Enterprise still
owns certify export, the deeper remediation report, and continuous
monitoring. This is a `FEATURE_TIERS` gate flip in
`packages/iris-core/iris_core/entitlements/features.py`
(`compliance_full_eval` capability already SHIPPABLE) — the eval engine
is framework-agnostic, so widening free coverage costs one dict entry
per framework, not new engineering.

Phased, not all-at-once: each phase is evaluated before the next one
widens free coverage further.

| Phase | Frameworks | Status | Notes |
|---|---|---|---|
| 1 | GDPR, HIPAA, EU AI Act | **Done** | `BUNDLE_GDPR`/`BUNDLE_HIPAA`/`BUNDLE_EU_AI_ACT` moved `Tier.PRO` → `Tier.FREE`. Full rule-set assessment (`iris compliance check --framework gdpr\|hipaa\|eu-ai-act`) is free; `--full` (`CLI_TEST_FULL_REPORT`), PDF/OSCAL/AIUC-1 export (`CERTIFICATION_READINESS_PDF`, `EVIDENCE_EXPORT_AUDITOR`), and continuous monitoring stay Enterprise-gated — unaffected by this change, verified in tests. |
| 2 | NIST AI RMF, FedRAMP Moderate | Backlog | Promote after Phase 1 has been evaluated. |
| 3 | CCPA/CPRA ADMT, China PIPL, Illinois AI Video, NYC LL 144 | Backlog | Employment/regional bundles — lower general-adoption leverage than Phase 2; revisit after Phase 2 data. |

Not in scope for this lever: AIUC-1, ISO 42001 (third-party
certification artifacts, not point-in-time self-assessment — the
export itself is the product, not a preview wall).

## Console UX follow-ups (not capability promotions)

| Item | Status | Notes |
|---|---|---|
| identity_graph_redesign | Shippable | IRIS color tokens, radial layout, blast radius |
| integrations_api_wired | Shippable | Real API via React Query |
| theme_light_dark | Shippable | Light default, dark toggle |
| onboarding_profiler | Shippable | 5-question industry intake |
| otel_export | Shippable | AARM R8 OTLP export |
| aiuc1_evidence_package | Shippable | PDF + HTML Schellman-ready |
| aarm_core_conformant | In progress | R1–R9 partial; CSA TWG review pending |
| aarm_extended_conformant | Backlog | R7–R9 not complete |
| multi_agent_chains | Shippable | session_id chain grouping |
| feature-flag-system-reconciliation | Backlog | Merge `featureFlags.jsx` (UI visibility) with `launch_gate.py` CAPABILITY_FLAGS (API/CLI enforcement) once RBAC lands — keep layers distinct until then. |
| analyzeRuntimeBehavior backend | Backlog | `RuntimeSecurityPanel` and Interceptor behavior tab call `iris.functions.invoke('analyzeRuntimeBehavior')` — needs real serverless/backend implementation (confirmed needed by two pages). |
| ai_sensor_integration | Backlog | Successor to deleted `SensorIntegrations` / `SensorIntegrationsDetail` — net-new design feeding cloud security findings into Cedar evaluation context, not generic EDR dashboards. |
| certify_export from Reporting.jsx | Backlog | Track A2 (`certify_export`) should start from `Reporting.jsx` jsPDF generation code, not greenfield — compare with `Reports.jsx` before merging. |
| developer-portal-scope | Backlog | `DeveloperPortal.jsx` — product decision: delete or narrow to CLI/SDK command reference only. |

## AGT-repositioning follow-ups (flagged, not yet spec'd)

Explicit scope boundaries drawn during the five AGT-repositioning phases.
Each is real, deliberately
deferred rather than silently dropped, and none has a written spec yet.
Write one before promoting into a ranked Track A/B row above.

| Item | Status | Notes |
|---|---|---|
| workload_eval_framework_trigger_gap | Backlog | `applicable_frameworks()` (`packages/iris-core/iris_core/compliance/workload_eval.py`) only triggers 10 of the 14 advertised regulatory frameworks — `fedramp` and several `regulatory/registry.json` bundles (`colorado-mental-health-ai`, `nyc-ll144`, etc.) have no trigger rule, reachable only via `iris compliance check --framework <id>` directly, never via `iris compliance scan`/WorkloadProfile inference. Pre-existing, spotted during Phase 2/3. |
| fedramp_evidence_package_depth | Backlog | FedRAMP auditor evidence packages run through the identical generic pipeline as every other framework (`reports/service.py::auditor_package()`) — no deeper NIST 800-53 control-family or authorization-boundary evidence than HIPAA/SOC 2 get. Genuine differentiation needs real subject-matter authorization-boundary content authored by someone with FedRAMP expertise — not something to fabricate. Flagged in Phase 4, explicitly not attempted. |
| auditor_package_preview_console_ui | Backlog | The free-tier auditor-package preview (Phase 4, `POST /reports/auditor-package` unentitled path) has no IRIS Cloud Console UI surface — API + data model only. |
| regulatory_alerts_slack_email_delivery | Backlog | Continuous regulatory monitoring (Phase 5) ships webhook delivery only. Slack/email are natural follow-ups — `iris_core.drift.notifier`'s pattern (Block Kit, smtplib) is the template — but each needs its own content rendering, not direct reuse. |
| regulatory_alerts_console_ui | Backlog | No IRIS Cloud Console UI to subscribe to or browse regulatory-change alerts (`/monitoring/regulatory-alerts*`) — API + data model only. |
| regulatory_watch_production_scheduling | Backlog | `POST /admin/monitoring/regulatory-watch/run` is a real, tested, idempotent job function + admin-triggered endpoint, but nothing invokes it on a schedule in production. No cron/worker process exists anywhere in `iris-cloud-console-api` to provision one against (confirmed during Phase 5 research). Wiring an actual periodic trigger — hosting-platform cron, a scheduled GitHub Actions workflow hitting the endpoint (the same shape `docs/gha/sre.yml` already uses for customer-facing checks) — is an ops/deployment decision, not a code change. |

## Tokenomics follow-ups (flagged during Phase 6a)

| Item | Status | Notes |
|---|---|---|
| streaming_cost_tracking_gap | Backlog | `.stream()` / `async def stream()` on both `iris-anthropic` and `iris-openai` adapter clients call `_govern_kwargs()` (policy check) but never call `record_llm_cost_async()` — streamed calls today produce zero cost data, a real gap in `iris cost`'s "per-run breakdown" promise. Fixing it means accumulating a final usage object from a provider-specific stream iterator across 4 methods in 2 packages — real regression risk to already-shipped adapter behavior, deliberately deferred rather than attempted inside Phase 6a. |
| cost_anomaly_slack_notifier | Backlog | `DriftReport.new_cost_anomalies`/`resolved_cost_anomalies` (Phase 6b) are populated, diffed, and surfaced in `iris drift check`'s CLI table, but `DriftNotifier.notify_slack()` (`packages/iris-core/iris_core/drift/notifier.py`) is hand-built per `DriftReport` field today and doesn't render them in its Block Kit payload — separate content-authoring work, not a data-model change. |

## OSS mirror follow-ups (flagged while resolving the engine/evidence/models/drift gap)

| Item | Status | Notes |
|---|---|---|
| oss_mirror_import_closure | Backlog | `packages/iris-core/iris_core/{engine,evidence,models,drift}` (added to the GitHub mirror in `fix/oss-boundary-cost-governance-mirror`) import from `compliance/`, `dlp/`, `hitl/`, `org_policy/`, none of which are (fully) mirrored — `compliance/` in particular is deliberately not a full-directory OSS grant since the framework-bundle catalog is a paid differentiator. The public GitHub source tree therefore has real `import` statements pointing at modules absent from that tree; the installable PyPI wheel (`iris-security-core`) is complete and unaffected. Closing this needs a deliberate, separately-scoped OSS/paid classification pass over `compliance/`, `dlp/`, `hitl/`, `org_policy/` (likely per-file, not per-directory, given `compliance/`'s mixed OSS/paid contents) — not attempted as part of the mirror fix. See `packages/iris-core/OSS_BOUNDARY.md`'s "Known limitation" note. |

## Trust-lifecycle follow-ups (flagged during Phase 7c)

| Item | Status | Notes |
|---|---|---|
| trust_lifecycle_auditor_package | Backlog | Phase 7c's `packages/iris-cloud-console-api/iris_cloud_console_api/trust/` module gives queryable, timestamped, append-only trust history per agent (`GET /trust/agent-history/{agent_id}`), which is already genuinely auditable — but it doesn't yet produce a hash-verified, downloadable "auditor package" the way `reports/service.py`'s `auditor_package()` does for compliance evidence (Phase 4): `package_hash()` + persisted `ReportArtifact` (tamper-evident, re-verified on read) + `reports/pdf.py`'s `render_auditor_pdf()`. Wiring a `report_type="trust_lifecycle"` through that existing machinery (rather than building a parallel export/hash system) is the natural follow-up, deliberately not folded into the already-multi-file 7c PR. |

## Dependency follow-ups (flagged during Phase 7c's standing dependency audit)

| Item | Status | Notes |
|---|---|---|
| react_router_v7_migration | Backlog | `npm audit` on `packages/iris-cloud-console` and `packages/iris-admin-console` flags `react-router`/`react-router-dom` 6.30.4 (moderate: CVE-2025-68470-bypass open redirect via backslash in `<Link>`/`useNavigate`, and an arbitrary constructor-injection issue in SSR error deserialization). No patched release exists anywhere in the 6.x line — the fix is only in 7.18.1+, a major version with breaking API changes. `npm audit fix` confirmed it can't resolve this within the declared `^6.26.0` range (no lockfile changes applied). Both apps still build cleanly on 6.30.4, and neither has route-level test coverage to safety-net a v6→v7 migration, so it's deliberately not attempted inside this backend-feature PR — needs its own dedicated, tested migration pass across both console apps. |
