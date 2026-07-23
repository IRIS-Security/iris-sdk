"""
PolicyCompiler: natural language → Cedar policy.

This is the architect's permit office. The developer writes what they want
the agent to do in plain English. The compiler:
  1. Sends the intent to the configured LLM (local or API)
  2. Generates valid Cedar syntax
  3. Validates against the IRIS compliance framework
  4. Returns the Cedar + a plain-English explanation of any conflicts

The Cedar is never the developer's problem to write.
They describe intent. IRIS compiles.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path
import json
import os
import re

from iris_core.models.passport import AgentPassport, ComplianceTag
from iris_core.models.policy import Violation, Severity
from iris_core.compliance.registry import ComplianceRegistry


CEDAR_SYSTEM_PROMPT = """
You are the IRIS policy compiler. You convert developer intent written in
plain English into valid Cedar policy syntax for the IRIS AI agent governance
platform.

Cedar policy rules:
- Use permit() and forbid() statements
- Principal is always AgentPassport::"<agent-name>"
- Actions: Action::"call", Action::"read", Action::"write", Action::"execute"
- Resources: API::"<name>", DataClass::"<class>", Tool::"<name>", Storage::"<name>"
- Context fields: environment, data_region, destination_region, data_classification,
  user_consent_logged, user_email, user_role, user_authenticated
- Namespace: iris::

Always output:
1. The Cedar policy wrapped in ```cedar ... ```
2. A plain-English explanation of each rule
3. The compliance frameworks each rule satisfies
4. Any conflicts with known compliance requirements

Never expose Cedar syntax errors to the developer — explain issues in plain English.
"""

DEFAULT_MODELS: Dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "google": "gemini-2.0-flash",
    "mistral": "mistral-large-latest",
    "cohere": "command-r-plus",
    "groq": "llama-3.3-70b-versatile",
    "together": "meta-llama/Llama-3-70b",
    "ollama": "llama3.2",
}

def generate_rbac_cedar(passport: AgentPassport) -> str:
    """Generate Cedar user RBAC rules from passport role configuration."""
    if not passport.allowed_user_roles:
        return ""
    roles_literal = ", ".join(f'"{role}"' for role in passport.allowed_user_roles)
    roles_list = f"[{roles_literal}]"
    return (
        "// IRIS user RBAC — auto-generated (do not edit)\n"
        "permit(principal, action, resource)\n"
        f"when {{ context.user_role in {roles_list} }};\n\n"
        "forbid(principal, action, resource)\n"
        f"unless {{ context.user_role in {roles_list} }};\n"
    )


def append_rbac_to_policy(cedar_policy: str, passport: AgentPassport) -> str:
    """Append auto-generated user RBAC Cedar rules when roles are configured."""
    rbac = generate_rbac_cedar(passport)
    if not rbac:
        return cedar_policy
    base = cedar_policy.rstrip()
    if base:
        return f"{base}\n\n{rbac}"
    return rbac


LLM_REQUIRED_ERROR = """
┌─ IRIS Policy Compiler — LLM Required ─────────────────────┐
│                                                             │
│  iris policy compile needs an LLM to compile your intent.  │
│                                                             │
│  Option 1 — Anthropic (Claude):                            │
│    pip install iris-security-sdk[anthropic]                │
│    export ANTHROPIC_API_KEY=your-key                       │
│                                                             │
│  Option 2 — OpenAI (GPT-4o):                               │
│    pip install iris-security-sdk[openai]                   │
│    export OPENAI_API_KEY=your-key                          │
│                                                             │
│  Option 3 — Google (Gemini):                               │
│    pip install iris-security-sdk[google]                   │
│    export GOOGLE_API_KEY=your-key                          │
│                                                             │
│  Option 4 — Mistral:                                       │
│    pip install iris-security-sdk[mistral]                  │
│    export MISTRAL_API_KEY=your-key                         │
│                                                             │
│  Option 5 — Groq (Llama, fastest inference):               │
│    pip install iris-security-sdk[groq]                     │
│    export GROQ_API_KEY=your-key                            │
│                                                             │
│  Option 6 — Any provider via LiteLLM:                      │
│    pip install iris-security-sdk[litellm]                  │
│    iris policy compile --agent my-agent \\                  │
│      --litellm-model ollama/llama3.2                       │
│    (supports 100+ providers including Ollama, Bedrock,     │
│     Azure, HuggingFace, Together, and more)                │
│                                                             │
│  Option 7 — Ollama locally (free, no API key):             │
│    brew install ollama && ollama pull llama3.2             │
│    ollama serve                                             │
│    pip install iris-security-sdk[litellm]                  │
│    iris policy compile --agent my-agent \\                  │
│      --litellm-model ollama/llama3.2                       │
│                                                             │
│  Option 8 — Bring your own LLM function (Python SDK):      │
│    from iris_core.engine.compiler import PolicyCompiler     │
│    compiler = PolicyCompiler(custom_llm=my_llm_fn)         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
"""


@dataclass
class CompilationResult:
    cedar_policy: str
    intent_markdown: str
    compliance_refs: List[str]
    violations: List[Violation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    success: bool = True

    def has_blocking_violations(self) -> bool:
        return any(v.severity == Severity.CRITICAL for v in self.violations)


class PolicyCompiler:
    """
    Compiles natural language policy intent to Cedar.

    Supports any LLM via auto-detected API keys, LiteLLM, or a custom callable.
    Keys are read from environment variables and never stored by IRIS.
    """

    def __init__(
        self,
        compliance_registry: Optional[ComplianceRegistry] = None,
        llm_backend: Optional[str] = None,
        model: Optional[str] = None,
        custom_llm: Optional[Callable[[str], str]] = None,
        litellm_model: Optional[str] = None,
    ):
        self._registry = compliance_registry or ComplianceRegistry()
        self._custom_llm = custom_llm
        self._litellm_model = litellm_model
        self._mode: str

        if custom_llm is not None:
            self._mode = "custom"
            self._llm_backend = "custom"
            self._model = model or "custom"
        elif litellm_model is not None:
            self._mode = "litellm"
            self._llm_backend = "litellm"
            self._model = litellm_model
        elif llm_backend is not None:
            self._mode = "native"
            self._llm_backend = llm_backend
            self._model = model or DEFAULT_MODELS.get(llm_backend, llm_backend)
        else:
            self._mode = "native"
            self._llm_backend, default_model = self._auto_detect_backend()
            self._model = model or default_model

    def compile(
        self,
        intent: str,
        passport: AgentPassport,
        active_bundles: Optional[List[ComplianceTag]] = None,
        dry_run: bool = False,
    ) -> CompilationResult:
        """
        Compile natural language intent to Cedar policy.

        Args:
            intent: Plain English description of what the agent is allowed to do.
                    Example: "This agent can only read customer data in the EU
                    and must never write to any external API without user consent."
            passport: The agent's passport (for context on identity and env).
            active_bundles: Compliance frameworks to validate against.
                            Defaults to the compliance_tags on the passport.
            dry_run: When True, compile only — callers must not write policy.cedar
                     or policy-intent.md to disk (used by iris policy diff).

        Returns:
            CompilationResult with Cedar policy, markdown intent, and any violations.
        """
        bundles = active_bundles or passport.compliance_tags
        bundle_rules = self._registry.get_rules_for_bundles(bundles)

        prompt = self._build_prompt(intent, passport, bundle_rules)
        raw_response = self._call_llm(prompt)
        return self._parse_response(raw_response, intent, passport, bundles, dry_run=dry_run)

    def compile_from_file(
        self,
        intent_file: Path,
        passport: AgentPassport,
    ) -> CompilationResult:
        """Compile from a policy-intent.md file on disk."""
        if not intent_file.exists():
            raise FileNotFoundError(
                f"Intent file not found: {intent_file}\n"
                f"Create a policy-intent.md file describing what your agent is allowed to do."
            )
        intent = intent_file.read_text()
        return self.compile(intent, passport)

    def _auto_detect_backend(self) -> tuple[str, str]:
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic", DEFAULT_MODELS["anthropic"]
        if os.environ.get("OPENAI_API_KEY"):
            return "openai", DEFAULT_MODELS["openai"]
        if os.environ.get("GOOGLE_API_KEY"):
            return "google", DEFAULT_MODELS["google"]
        if os.environ.get("MISTRAL_API_KEY"):
            return "mistral", DEFAULT_MODELS["mistral"]
        if os.environ.get("COHERE_API_KEY"):
            return "cohere", DEFAULT_MODELS["cohere"]
        if os.environ.get("GROQ_API_KEY"):
            return "groq", DEFAULT_MODELS["groq"]
        if os.environ.get("TOGETHER_API_KEY"):
            return "together", DEFAULT_MODELS["together"]
        if os.environ.get("OLLAMA_HOST") or self._detect_ollama():
            return "ollama", DEFAULT_MODELS["ollama"]
        raise EnvironmentError(LLM_REQUIRED_ERROR.strip())

    def _detect_ollama(self) -> bool:
        try:
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def _build_prompt(
        self,
        intent: str,
        passport: AgentPassport,
        bundle_rules: Dict[str, Any],
    ) -> str:
        return f"""
Agent context:
- Name: {passport.name}
- Owner: {passport.owner} ({passport.team})
- Data classification: {passport.data_classification.value}
- Environments: {[e.value for e in passport.environments]}
- Is high-risk AI (Colorado AI Act): {passport.is_high_risk_ai}
- Compliance tags: {[t.value for t in passport.compliance_tags]}
- Allowed user roles: {passport.allowed_user_roles or ["any authenticated user"]}
- Require user authentication: {passport.require_user_authentication}

Developer intent (plain English):
{intent}

Active compliance rules to validate against:
{json.dumps(bundle_rules, indent=2)}

Generate the Cedar policy for this agent. Validate it against the compliance
rules above. If any intent violates a compliance rule, explain the conflict
in plain English and provide the compliant alternative.
"""

    def _call_llm(self, prompt: str) -> str:
        if self._mode == "custom":
            return self._custom_llm(prompt)
        if self._mode == "litellm":
            return self._call_litellm(prompt)

        dispatch = {
            "anthropic": self._call_anthropic,
            "openai": self._call_openai,
            "google": self._call_google,
            "mistral": self._call_mistral,
            "cohere": self._call_cohere,
            "groq": self._call_groq,
            "together": self._call_together,
            "ollama": self._call_ollama,
        }
        handler = dispatch.get(self._llm_backend)
        if handler is None:
            raise ValueError(
                f"Unknown LLM backend: {self._llm_backend}. "
                f"Supported: {', '.join(sorted(dispatch))}, litellm, custom_llm"
            )
        return handler(prompt)

    def _call_litellm(self, prompt: str) -> str:
        try:
            import litellm
            response = litellm.completion(
                model=self._litellm_model,
                messages=[
                    {"role": "system", "content": CEDAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content
        except ImportError:
            raise ImportError(
                "litellm not installed. Run: pip install iris-security-sdk[litellm]\n"
                "LiteLLM supports 100+ LLM providers including Ollama,\n"
                "Bedrock, Azure, HuggingFace, Mistral, and more."
            )

    def _call_anthropic(self, prompt: str) -> str:
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise EnvironmentError(
                    "ANTHROPIC_API_KEY not set.\n"
                    "Set it with: export ANTHROPIC_API_KEY=your-key\n"
                    "Or add it to ~/.iris/config.yaml"
                )
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=CEDAR_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except ImportError:
            raise ImportError(
                "anthropic not installed. Run: pip install iris-security-sdk[anthropic]"
            )

    def _call_openai(self, prompt: str) -> str:
        try:
            from openai import OpenAI
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise EnvironmentError("OPENAI_API_KEY not set.")
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": CEDAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content
        except ImportError:
            raise ImportError(
                "openai not installed. Run: pip install iris-security-sdk[openai]"
            )

    def _call_google(self, prompt: str) -> str:
        try:
            import google.generativeai as genai
            api_key = os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                raise EnvironmentError("GOOGLE_API_KEY not set.")
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                self._model,
                system_instruction=CEDAR_SYSTEM_PROMPT,
            )
            response = model.generate_content(prompt)
            return response.text
        except ImportError:
            raise ImportError(
                "google-genai not installed. Run: pip install iris-security-sdk[google]"
            )

    def _call_mistral(self, prompt: str) -> str:
        try:
            from mistralai import Mistral
            client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
            response = client.chat.complete(
                model=self._model,
                messages=[
                    {"role": "system", "content": CEDAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content
        except ImportError:
            raise ImportError(
                "mistralai not installed. Run: pip install iris-security-sdk[mistral]"
            )

    def _call_cohere(self, prompt: str) -> str:
        try:
            import cohere
            client = cohere.ClientV2(api_key=os.environ["COHERE_API_KEY"])
            response = client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": CEDAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.message.content[0].text
        except ImportError:
            raise ImportError(
                "cohere not installed. Use LiteLLM instead:\n"
                "  pip install iris-security-sdk[litellm]\n"
                "  iris policy compile --litellm-model cohere/command-r-plus"
            )

    def _call_groq(self, prompt: str) -> str:
        try:
            from groq import Groq
            client = Groq(api_key=os.environ["GROQ_API_KEY"])
            response = client.chat.completions.create(
                model=self._model or "llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": CEDAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content
        except ImportError:
            raise ImportError(
                "groq not installed. Run: pip install iris-security-sdk[groq]"
            )

    def _call_together(self, prompt: str) -> str:
        try:
            from together import Together
            client = Together(api_key=os.environ["TOGETHER_API_KEY"])
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": CEDAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content
        except ImportError:
            raise ImportError(
                "together not installed. Use LiteLLM instead:\n"
                "  pip install iris-security-sdk[litellm]\n"
                "  iris policy compile --litellm-model together_ai/meta-llama/Llama-3-70b"
            )

    def _call_ollama(self, prompt: str) -> str:
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx not installed. Run: pip install httpx\n"
                "Or use LiteLLM for Ollama: pip install iris-security-sdk[litellm]"
            )

        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not host.startswith("http"):
            host = f"http://{host}"

        response = httpx.post(
            f"{host.rstrip('/')}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": CEDAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]

    def _parse_response(
        self,
        raw: str,
        intent: str,
        passport: AgentPassport,
        bundles: List[ComplianceTag],
        dry_run: bool = False,
    ) -> CompilationResult:
        cedar_match = re.search(r"```cedar\n(.*?)```", raw, re.DOTALL)
        cedar_policy = cedar_match.group(1).strip() if cedar_match else ""
        cedar_policy = append_rbac_to_policy(cedar_policy, passport)

        intent_md = "" if dry_run else self._build_intent_markdown(intent, passport, bundles)

        violations = []
        if "violation" in raw.lower() or "conflict" in raw.lower():
            violations.append(Violation(
                rule_id="COMPILER-WARN-001",
                severity=Severity.HIGH,
                message="Policy compiler detected compliance conflicts. Review required.",
                compliance_refs=[b.value for b in bundles],
                remediation="Review the compiler output and resolve conflicts before committing.",
            ))

        return CompilationResult(
            cedar_policy=cedar_policy,
            intent_markdown=intent_md,
            compliance_refs=[b.value for b in bundles],
            violations=violations,
            success=bool(cedar_policy),
        )

    def _build_intent_markdown(
        self,
        intent: str,
        passport: AgentPassport,
        bundles: List[ComplianceTag],
    ) -> str:
        """
        Generate the policy-intent.md file — the source of truth and
        Colorado AI Act transparency disclosure for this agent.
        """
        return f"""# Policy Intent — {passport.name}

> This document is the source of truth for this agent's policy.
> The Cedar policy (`policy.cedar`) is auto-generated from this file by IRIS.
> Do not edit `policy.cedar` directly — edit this file and run `iris policy compile`.

## Agent identity
- **Name**: {passport.name}
- **Owner**: {passport.owner} ({passport.team})
- **Data classification**: {passport.data_classification.value}
- **High-risk AI (Colorado AI Act)**: {passport.is_high_risk_ai}

## Developer intent

{intent}

## Active compliance frameworks

{chr(10).join(f'- {b.value}' for b in bundles)}

## Colorado AI Act disclosure (SB 26-189)

This agent {"is" if passport.is_high_risk_ai else "is not"} classified as covered
automated decision-making technology (ADMT) under the Colorado AI Act
(effective January 1, 2027; replaces SB 24-205).

{"As a covered ADMT system, this agent is subject to transparency, notice, and record retention requirements under SB 26-189." if passport.is_high_risk_ai else ""}

*Generated by IRIS policy compiler. Last updated: auto.*
"""
