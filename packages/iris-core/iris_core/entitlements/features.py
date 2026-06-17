"""
Single source of truth for every IRIS feature and its tier.

To add a new Pro feature: add one line here.
To move a feature from Pro to Free: change its tier here.
Nothing else needs to change anywhere in the codebase.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict


class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Feature(str, Enum):
    # ── FREE TIER ─────────────────────────────────────────────
    # Core SDK
    AGENT_REGISTRATION = "agent_registration"
    POLICY_COMPILE = "policy_compile"
    POLICY_DIFF = "policy_diff"
    RUNTIME_ENFORCEMENT = "runtime_enforcement"
    SCAN_DISCOVER = "scan_discover"
    SCAN_GOVERN = "scan_govern"
    CEDAR_ENGINE = "cedar_engine"
    DLP_SCANNER = "dlp_scanner"
    # Free compliance bundles
    BUNDLE_COLORADO_AI_ACT = "bundle_colorado_ai_act"
    BUNDLE_COLORADO_CHATBOT = "bundle_colorado_chatbot"
    BUNDLE_COLORADO_HEALTH_AI = "bundle_colorado_health_ai"
    BUNDLE_COLORADO_MENTAL_HEALTH = "bundle_colorado_mental_health"
    # Free CLI commands
    CLI_STATUS = "cli_status"
    CLI_EXPLAIN = "cli_explain"
    CLI_WATCH = "cli_watch"
    CLI_FRAMEWORK_SUGGEST = "cli_framework_suggest"
    CLI_COMPLIANCE_CHECK = "cli_compliance_check"
    CLI_COMPLIANCE_ASSESS = "cli_compliance_assess"
    CLI_DRIFT_SNAPSHOT = "cli_drift_snapshot"
    CLI_DRIFT_CHECK = "cli_drift_check"
    CLI_COST_REPORT_BASIC = "cli_cost_report_basic"
    CLI_REGULATORY_CHECK = "cli_regulatory_check"
    # Free Evidence Vault (30-day local)
    VAULT_LOCAL = "vault_local"
    VAULT_30_DAY_RETENTION = "vault_30_day_retention"
    VAULT_BASIC_REPORT = "vault_basic_report"
    # Free iris test (score + top 3 gaps only)
    CLI_TEST_SCORE = "cli_test_score"
    CLI_TEST_TOP3_GAPS = "cli_test_top3_gaps"
    # Free red-team (summary only)
    RED_TEAM_SUMMARY = "red_team_summary"

    # ── PRO TIER ──────────────────────────────────────────────
    # Pro compliance bundles
    BUNDLE_NIST_AI_RMF = "bundle_nist_ai_rmf"
    BUNDLE_FEDRAMP_MODERATE = "bundle_fedramp_moderate"
    BUNDLE_HIPAA = "bundle_hipaa"
    BUNDLE_SOC2 = "bundle_soc2"
    BUNDLE_GDPR = "bundle_gdpr"
    BUNDLE_EU_AI_ACT = "bundle_eu_ai_act"
    BUNDLE_CCPA_ADMT = "bundle_ccpa_admt"
    BUNDLE_CHINA_PIPL = "bundle_china_pipl"
    # Pro iris test (full report)
    CLI_TEST_FULL_REPORT = "cli_test_full_report"
    CLI_TEST_ALL_GAPS = "cli_test_all_gaps"
    CLI_TEST_PROGRESS_TRACKING = "cli_test_progress_tracking"
    CLI_TEST_PDF_EXPORT = "cli_test_pdf_export"
    # Pro red-team (full findings)
    RED_TEAM_FULL_FINDINGS = "red_team_full_findings"
    RED_TEAM_BYPASS_DETAILS = "red_team_bypass_details"
    RED_TEAM_REMEDIATION = "red_team_remediation"
    # Pro Evidence Vault
    VAULT_UNLIMITED_RETENTION = "vault_unlimited_retention"
    VAULT_CLOUD_SYNC = "vault_cloud_sync"
    VAULT_PDF_EXPORT = "vault_pdf_export"
    VAULT_TAMPER_EVIDENT = "vault_tamper_evident"
    VAULT_3_YEAR_RETENTION = "vault_3_year_retention"
    VAULT_GDPR_REDACTION = "vault_gdpr_redaction"
    # Pro infrastructure
    K8S_SIDECAR = "k8s_sidecar"
    HITL_GATE = "hitl_gate"
    SCM_ORG_SCANNER = "scm_org_scanner"
    SCM_PR_COMMENTS = "scm_pr_comments"
    GITHUB_APP = "github_app"
    GITLAB_INTEGRATION = "gitlab_integration"
    # Pro alerting
    DRIFT_SLACK_ALERT = "drift_slack_alert"
    DRIFT_EMAIL_ALERT = "drift_email_alert"
    DRIFT_WEBHOOK_ALERT = "drift_webhook_alert"
    COST_ANOMALY_ALERT = "cost_anomaly_alert"
    COST_ORG_SUMMARY = "cost_org_summary"
    COST_TEAM_ROLLUP = "cost_team_rollup"
    # Pro access control
    TEAM_RBAC = "team_rbac"
    SSO = "sso"
    USER_LEVEL_RBAC = "user_level_rbac"
    # Pro reporting
    CERTIFICATION_READINESS_PDF = "certification_readiness_pdf"
    EVIDENCE_EXPORT_CSV = "evidence_export_csv"
    POLICY_CATALOG_EXPORT = "policy_catalog_export"

    # ── ENTERPRISE TIER ───────────────────────────────────────
    CUSTOM_COMPLIANCE_BUNDLE = "custom_compliance_bundle"
    DEDICATED_SUPPORT = "dedicated_support"
    SLA_GUARANTEE = "sla_guarantee"
    CUSTOM_PRICING = "custom_pricing"
    AUDIT_ASSISTANCE = "audit_assistance"
    MULTI_TENANT = "multi_tenant"


FEATURE_TIERS: Dict[Feature, Tier] = {
    # All FREE features
    Feature.AGENT_REGISTRATION: Tier.FREE,
    Feature.POLICY_COMPILE: Tier.FREE,
    Feature.POLICY_DIFF: Tier.FREE,
    Feature.RUNTIME_ENFORCEMENT: Tier.FREE,
    Feature.SCAN_DISCOVER: Tier.FREE,
    Feature.SCAN_GOVERN: Tier.FREE,
    Feature.CEDAR_ENGINE: Tier.FREE,
    Feature.DLP_SCANNER: Tier.FREE,
    Feature.BUNDLE_COLORADO_AI_ACT: Tier.FREE,
    Feature.BUNDLE_COLORADO_CHATBOT: Tier.FREE,
    Feature.BUNDLE_COLORADO_HEALTH_AI: Tier.FREE,
    Feature.BUNDLE_COLORADO_MENTAL_HEALTH: Tier.FREE,
    Feature.CLI_STATUS: Tier.FREE,
    Feature.CLI_EXPLAIN: Tier.FREE,
    Feature.CLI_WATCH: Tier.FREE,
    Feature.CLI_FRAMEWORK_SUGGEST: Tier.FREE,
    Feature.CLI_COMPLIANCE_CHECK: Tier.FREE,
    Feature.CLI_COMPLIANCE_ASSESS: Tier.FREE,
    Feature.CLI_DRIFT_SNAPSHOT: Tier.FREE,
    Feature.CLI_DRIFT_CHECK: Tier.FREE,
    Feature.CLI_COST_REPORT_BASIC: Tier.FREE,
    Feature.CLI_REGULATORY_CHECK: Tier.FREE,
    Feature.VAULT_LOCAL: Tier.FREE,
    Feature.VAULT_30_DAY_RETENTION: Tier.FREE,
    Feature.VAULT_BASIC_REPORT: Tier.FREE,
    Feature.CLI_TEST_SCORE: Tier.FREE,
    Feature.CLI_TEST_TOP3_GAPS: Tier.FREE,
    Feature.RED_TEAM_SUMMARY: Tier.FREE,
    # All PRO features
    Feature.BUNDLE_NIST_AI_RMF: Tier.PRO,
    Feature.BUNDLE_FEDRAMP_MODERATE: Tier.PRO,
    Feature.BUNDLE_HIPAA: Tier.PRO,
    Feature.BUNDLE_SOC2: Tier.PRO,
    Feature.BUNDLE_GDPR: Tier.PRO,
    Feature.BUNDLE_EU_AI_ACT: Tier.PRO,
    Feature.BUNDLE_CCPA_ADMT: Tier.PRO,
    Feature.BUNDLE_CHINA_PIPL: Tier.PRO,
    Feature.CLI_TEST_FULL_REPORT: Tier.PRO,
    Feature.CLI_TEST_ALL_GAPS: Tier.PRO,
    Feature.CLI_TEST_PROGRESS_TRACKING: Tier.PRO,
    Feature.CLI_TEST_PDF_EXPORT: Tier.PRO,
    Feature.RED_TEAM_FULL_FINDINGS: Tier.PRO,
    Feature.RED_TEAM_BYPASS_DETAILS: Tier.PRO,
    Feature.RED_TEAM_REMEDIATION: Tier.PRO,
    Feature.VAULT_UNLIMITED_RETENTION: Tier.PRO,
    Feature.VAULT_CLOUD_SYNC: Tier.PRO,
    Feature.VAULT_PDF_EXPORT: Tier.PRO,
    Feature.VAULT_TAMPER_EVIDENT: Tier.PRO,
    Feature.VAULT_3_YEAR_RETENTION: Tier.PRO,
    Feature.VAULT_GDPR_REDACTION: Tier.PRO,
    Feature.K8S_SIDECAR: Tier.PRO,
    Feature.HITL_GATE: Tier.PRO,
    Feature.SCM_ORG_SCANNER: Tier.PRO,
    Feature.SCM_PR_COMMENTS: Tier.PRO,
    Feature.GITHUB_APP: Tier.PRO,
    Feature.GITLAB_INTEGRATION: Tier.PRO,
    Feature.DRIFT_SLACK_ALERT: Tier.PRO,
    Feature.DRIFT_EMAIL_ALERT: Tier.PRO,
    Feature.DRIFT_WEBHOOK_ALERT: Tier.PRO,
    Feature.COST_ANOMALY_ALERT: Tier.PRO,
    Feature.COST_ORG_SUMMARY: Tier.PRO,
    Feature.COST_TEAM_ROLLUP: Tier.PRO,
    Feature.TEAM_RBAC: Tier.PRO,
    Feature.SSO: Tier.PRO,
    Feature.USER_LEVEL_RBAC: Tier.PRO,
    Feature.CERTIFICATION_READINESS_PDF: Tier.PRO,
    Feature.EVIDENCE_EXPORT_CSV: Tier.PRO,
    Feature.POLICY_CATALOG_EXPORT: Tier.PRO,
    # All ENTERPRISE features
    Feature.CUSTOM_COMPLIANCE_BUNDLE: Tier.ENTERPRISE,
    Feature.DEDICATED_SUPPORT: Tier.ENTERPRISE,
    Feature.SLA_GUARANTEE: Tier.ENTERPRISE,
    Feature.CUSTOM_PRICING: Tier.ENTERPRISE,
    Feature.AUDIT_ASSISTANCE: Tier.ENTERPRISE,
    Feature.MULTI_TENANT: Tier.ENTERPRISE,
}

TIER_RANK = {Tier.FREE: 0, Tier.PRO: 1, Tier.ENTERPRISE: 2}

# Maps compliance bundle IDs (used in registry/CLI) to entitlement features.
BUNDLE_ID_TO_FEATURE: Dict[str, Feature] = {
    "colorado-ai-act": Feature.BUNDLE_COLORADO_AI_ACT,
    "colorado-ai-act-original": Feature.BUNDLE_COLORADO_AI_ACT,
    "colorado-chatbot": Feature.BUNDLE_COLORADO_CHATBOT,
    "colorado-health-ai": Feature.BUNDLE_COLORADO_HEALTH_AI,
    "colorado-mental-health-ai": Feature.BUNDLE_COLORADO_MENTAL_HEALTH,
    "nist-ai-rmf": Feature.BUNDLE_NIST_AI_RMF,
    "fedramp": Feature.BUNDLE_FEDRAMP_MODERATE,
    "fedramp-moderate": Feature.BUNDLE_FEDRAMP_MODERATE,
    "hipaa": Feature.BUNDLE_HIPAA,
    "soc2": Feature.BUNDLE_SOC2,
    "gdpr": Feature.BUNDLE_GDPR,
    "eu-ai-act": Feature.BUNDLE_EU_AI_ACT,
    "ccpa-admt": Feature.BUNDLE_CCPA_ADMT,
    "china-pipl": Feature.BUNDLE_CHINA_PIPL,
}
