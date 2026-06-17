"""Compliance MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from iris import AgentPassport
from iris_core.compliance.framework_check import run_framework_check
from iris_core.compliance.registry import ComplianceRegistry
from iris_core.entitlements import Feature
from iris_cli.framework_suggest import (
    Q1_CHOICES,
    Q2_CHOICES,
    Q4_CHOICES,
    Q8_CHOICES,
    Recommendation,
    _load_passport,
    _prefill_answers,
    build_recommendations,
)
from iris_cli.framework_test import _build_result, _framework_name, _render_markdown
from iris_mcp.tools._common import format_table, governance_dir, pro_gate, text_response


def get_free_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_compliance_check",
            description=(
                "Check an agent's compliance against a specific framework. "
                "Shows which rules pass, which fail, and exactly what to do "
                "to fix each failure."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "framework": {
                        "type": "string",
                        "description": "Framework ID (e.g. colorado-ai-act, hipaa)",
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "Optional — checks all agents if not provided",
                    },
                },
                "required": ["framework"],
            },
        ),
        Tool(
            name="iris_framework_suggest",
            description=(
                "Suggest which compliance frameworks apply to an agent based on "
                "what it does, what data it handles, and where its users are located. "
                "Call this when the developer asks 'which regulations apply to my agent?'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "What the agent does"},
                    "data_types": {
                        "type": "string",
                        "description": "What data it handles",
                    },
                    "user_locations": {
                        "type": "string",
                        "description": "Where users are located",
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "Optional — pre-fills from passport if provided",
                    },
                },
            },
        ),
    ]


def get_pro_tools() -> list[Tool]:
    return [
        Tool(
            name="iris_compliance_assess",
            description=(
                "Run an interactive compliance assessment for an agent. "
                "Generates a formal impact assessment stored in the Evidence Vault."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                    "assessor": {"type": "string"},
                },
                "required": ["agent_name"],
            },
        ),
        Tool(
            name="iris_certify",
            description=(
                "Generate a certification readiness report for an agent against "
                "a compliance framework. Shows the full evidence package suitable "
                "for an auditor."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "framework": {"type": "string"},
                    "agent_name": {"type": "string"},
                },
                "required": ["framework", "agent_name"],
            },
        ),
        Tool(
            name="iris_policy_catalog",
            description=(
                "Export the full policy catalog for all compliance frameworks "
                "available in IRIS."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def _discover_passports(gov_dir, agent_name: str | None) -> list[AgentPassport]:
    passports: list[AgentPassport] = []
    if agent_name:
        passport_file = gov_dir / agent_name / "passport.yaml"
        if passport_file.exists():
            passports.append(AgentPassport.from_yaml(passport_file.read_text()))
        return passports

    for passport_file in gov_dir.rglob("passport.yaml"):
        try:
            passports.append(AgentPassport.from_yaml(passport_file.read_text()))
        except Exception:
            continue
    return passports


def _answers_from_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    agent_name = arguments.get("agent_name")
    prefill = _prefill_answers(_load_passport(agent_name)) if agent_name else {}

    domain = str(arguments.get("domain", "")).lower()
    data_types = str(arguments.get("data_types", "")).lower()
    locations = str(arguments.get("user_locations", "")).lower()

    answers = dict(prefill)
    if domain:
        answers["agent_description"] = arguments.get("domain", "")
        if any(kw in domain for kw in ("hire", "loan", "medical", "credit", "insurance")):
            answers["q1"] = Q1_CHOICES[0]
            answers["q5"] = True
        elif any(kw in domain for kw in ("chat", "question", "support")):
            answers["q1"] = Q1_CHOICES[3]
        elif any(kw in domain for kw in ("summar", "classif", "rout")):
            answers["q1"] = Q1_CHOICES[1]

    if "health" in data_types or "phi" in data_types or "medical" in data_types:
        answers["q4"] = Q4_CHOICES[0]
    elif "financial" in data_types or "payment" in data_types:
        answers["q4"] = Q4_CHOICES[1]
    elif "pii" in data_types or "personal" in data_types or "email" in data_types:
        answers["q4"] = Q4_CHOICES[2]
    elif data_types:
        answers["q4"] = Q4_CHOICES[4]

    if "colorado" in locations:
        answers["q8"] = ["Colorado"]
    elif "california" in locations:
        answers["q8"] = ["California"]
    elif "china" in locations or "asia" in locations:
        answers["q8"] = ["Outside the US"]
    elif "eu" in locations or "europe" in locations:
        answers["q8"] = ["Outside the US"]
    elif locations:
        answers["q8"] = ["Other / multiple states"]

    if "federal" in domain or "government" in domain:
        answers["q6"] = True
        answers["q2"] = Q2_CHOICES[0]

    return answers


def _format_recommendations(recommendations: list[Recommendation]) -> str:
    applicable = [r for r in recommendations if r.status in ("REQUIRED", "RECOMMENDED")]
    if not applicable:
        return "No specific frameworks triggered. Colorado AI Act is a sensible default for US agents."

    rows = []
    for rec in applicable:
        rows.append([rec.framework, rec.tier, rec.status, rec.reason[:80]])
    table = format_table(["Framework", "Tier", "Status", "Reason"], rows)
    lines = ["Framework Recommendations", "", table, ""]
    for rec in applicable:
        if rec.command:
            lines.append(f"  • {rec.framework}: {rec.command}")
    return "\n".join(lines)


async def check(arguments: dict[str, Any]):
    framework = arguments.get("framework", "colorado-ai-act")
    gov_dir = governance_dir(arguments)
    passports = _discover_passports(gov_dir, arguments.get("agent_name"))
    if not passports:
        return text_response(
            "No agent passports found.\n"
            "Run iris_declare to register an agent first."
        )

    sections: list[str] = []
    for passport in passports:
        result = run_framework_check(passport, framework)
        if result.preview_only:
            sections.append(
                f"Agent: {passport.name}\n"
                f"Framework: {result.framework_name} (Pro preview — 3 controls shown)\n"
                f"Upgrade: iris license activate <your-key>\n"
            )
            for rule in result.rule_results:
                sections.append(f"  {rule.rule_id}  {rule.status}  {rule.name}")
            continue

        failures = [r for r in result.rule_results if r.status == "FAIL"]
        status = "PASS" if not failures else "FAIL"
        sections.append(f"Agent: {passport.name} — {status}")
        rows = []
        for rule in result.rule_results:
            fix = rule.remediation or ""
            rows.append([rule.rule_id, rule.severity, rule.status, fix[:60]])
        sections.append(format_table(["Rule", "Severity", "Status", "Remediation"], rows))
        sections.append("")

    return text_response("\n".join(sections).strip())


async def framework_suggest(arguments: dict[str, Any]):
    answers = _answers_from_arguments(arguments)
    if not answers.get("agent_description") and not answers.get("q1"):
        return text_response(
            "Provide domain, data_types, and user_locations so IRIS can recommend "
            "frameworks — or pass agent_name to pre-fill from an existing passport."
        )
    recommendations = build_recommendations(answers)
    return text_response(_format_recommendations(recommendations))


async def assess(arguments: dict[str, Any]):
    blocked = pro_gate(
        Feature.HITL_GATE,
        "iris compliance assess requires IRIS Pro.\n"
        "The assessment generates a formal impact assessment document that "
        "satisfies Colorado AI Act CO-002, EU AI Act Art 9, CCPA risk assessment, "
        "and PIPL Article 56 requirements.\n"
        "iris license activate <your-key> to unlock.",
    )
    if blocked:
        return text_response(blocked)

    agent = arguments["agent_name"]
    gov_dir = governance_dir(arguments) / agent
    passport_file = gov_dir / "passport.yaml"
    if not passport_file.exists():
        return text_response(f"No passport for '{agent}'. Run iris_declare first.")

    import uuid

    import yaml
    from iris_cli.assess import calculate_risk_level, generate_assessment_markdown

    questionnaire_answers = _prefill_answers(_load_passport(agent))
    if not questionnaire_answers:
        questionnaire_answers = {
            "q5": True,
            "q1": "Makes decisions that affect individual people (hiring, loans, medical, etc.)",
            "agent_description": f"MCP assessment for {agent}",
        }

    risk_level, findings, recommendations = calculate_risk_level(questionnaire_answers)
    assessment_id = f"IA-{agent}-{uuid.uuid4().hex[:8].upper()}"
    passport_data = yaml.safe_load(passport_file.read_text())
    owner = passport_data.get("spec", {}).get("owner", "unknown")
    assessed_by = arguments.get("assessor", "iris-mcp")

    assessment_md = generate_assessment_markdown(
        agent_name=agent,
        owner=owner,
        answers=questionnaire_answers,
        risk_level=risk_level,
        findings=findings,
        recommendations=recommendations,
        assessment_id=assessment_id,
        assessed_by=assessed_by,
    )
    assessment_file = gov_dir / "impact-assessment.md"
    assessment_file.write_text(assessment_md)
    passport_data.setdefault("spec", {})["evidence_vault_id"] = assessment_id
    passport_file.write_text(yaml.dump(passport_data, default_flow_style=False, sort_keys=False))

    return text_response(
        f"✓ Impact assessment generated for {agent}\n"
        f"Risk level: {risk_level}\n"
        f"Assessment ID: {assessment_id}\n"
        f"Saved: {assessment_file}\n\n"
        f"Next: iris_compliance_check with framework colorado-ai-act"
    )


async def certify(arguments: dict[str, Any]):
    blocked = pro_gate(
        Feature.CLI_TEST_FULL_REPORT,
        "iris certify requires IRIS Pro for the full certification report.\n"
        "iris license activate <your-key> to unlock.",
    )
    if blocked:
        return text_response(blocked)

    framework = arguments["framework"]
    agent_name = arguments["agent_name"]
    passport_path = governance_dir(arguments) / agent_name / "passport.yaml"
    if not passport_path.exists():
        return text_response(f"Passport not found: {passport_path}")

    passport = AgentPassport.from_yaml(passport_path.read_text())
    result = _build_result(framework, agent_name, passport)
    report = _render_markdown(result, has_pro=True)
    return text_response(
        f"IRIS Certification — {agent_name} / {_framework_name(framework)}\n\n"
        f"{report}"
    )


async def catalog(arguments: dict[str, Any]):
    blocked = pro_gate(
        Feature.POLICY_CATALOG_EXPORT,
        "iris policy catalog requires IRIS Pro.\n"
        "iris license activate <your-key> to unlock.",
    )
    if blocked:
        return text_response(blocked)

    from iris_core.compliance.registry import _BUNDLE_LOADERS, _is_paid_bundle

    registry = ComplianceRegistry()
    rows = []
    for bundle_id in sorted(_BUNDLE_LOADERS):
        rules = registry._load_bundle_rules(bundle_id)
        tier = "PRO" if _is_paid_bundle(bundle_id) else "FREE"
        rows.append([bundle_id, rules.get("full_name", bundle_id), tier, str(len(rules.get("rules", [])))])
    return text_response(
        "IRIS Policy Catalog\n\n"
        + format_table(["Bundle ID", "Name", "Tier", "Rules"], rows)
    )
