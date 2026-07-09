"""Offline workload detection for compliance intelligence scans."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_PROVIDER_IMPORTS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "generativeai": "google",
    "vertexai": "google",
    "azure": "azure",
    "bedrock": "aws",
    "boto3": "aws",
    "cohere": "cohere",
    "mistralai": "mistral",
}

_FRAMEWORK_IMPORTS = {
    "langchain": "langchain",
    "crewai": "crewai",
    "llama_index": "llama_index",
    "semantic_kernel": "semantic_kernel",
    "autogen": "autogen",
    "haystack": "haystack",
}

_MODEL_PATTERNS = [
    re.compile(r"gpt-4[a-z0-9.-]*", re.I),
    re.compile(r"gpt-3\.5[a-z0-9.-]*", re.I),
    re.compile(r"claude-[a-z0-9.-]+", re.I),
    re.compile(r"gemini-[a-z0-9.-]+", re.I),
    re.compile(r"text-embedding-[a-z0-9.-]+", re.I),
]

_MODEL_PROVIDER_PREFIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^gpt-", re.I), "openai"),
    (re.compile(r"^o[134]-", re.I), "openai"),
    (re.compile(r"^text-embedding-", re.I), "openai"),
    (re.compile(r"^claude-", re.I), "anthropic"),
    (re.compile(r"^gemini-", re.I), "google"),
    (re.compile(r"^gemini/", re.I), "google"),
    (re.compile(r"^text-bison", re.I), "google"),
    (re.compile(r"^command", re.I), "cohere"),
    (re.compile(r"^mistral", re.I), "mistral"),
    (re.compile(r"^llama", re.I), "meta"),
    (re.compile(r"^amazon\.", re.I), "aws"),
    (re.compile(r"^anthropic\.", re.I), "anthropic"),
    (re.compile(r"^azure/", re.I), "azure"),
    (re.compile(r"^vertex_ai/", re.I), "google"),
    (re.compile(r"^openai/", re.I), "openai"),
    (re.compile(r"^bedrock/", re.I), "aws"),
]

_DATA_CATEGORY_PATTERNS = {
    # Note: regulation/framework names (hipaa, pci, gdpr, ...) are deliberately
    # excluded here. A compliance tool's own source legitimately talks *about*
    # those frameworks (rule engines, questionnaire copy, requirement labels)
    # without ever handling the regulated data itself, so a bare framework
    # name is not evidence of a data category — only concrete data-field
    # vocabulary is. Likewise "passport" alone is excluded: this codebase's
    # own AgentPassport/passport.yaml artifact naming collides with the word
    # far more often than it means travel-document PII.
    "pii": re.compile(
        r"\b(ssn|social_security|date_of_birth|dob|passport_number|passport_no|"
        r"email_address|phone_number|first_name|last_name|address_line|national_id)\b",
        re.I,
    ),
    "phi": re.compile(
        r"\b(patient_id|medical_record|diagnosis|icd_?10|health_record|"
        r"prescription|mrn|protected_health)\b",
        re.I,
    ),
    "financial": re.compile(
        r"\b(credit_card|card_number|bank_account|routing_number|iban|"
        r"account_balance|transaction_amount)\b",
        re.I,
    ),
    "biometric": re.compile(
        r"\b(fingerprint|face_id|retina_scan|voice_print)\b",
        re.I,
    ),
}

# Adjacency required (after removing whitespace/quote noise) for a data-field
# term to count as source code actually *handling* that field, rather than
# just naming it in a docstring, questionnaire string, or keyword list — an
# assignment, a type annotation, or a dict/JSON key all qualify; a bare
# occurrence inside a comma-separated keyword list or prose sentence does
# not.
_CODE_ASSIGNMENT_CONTEXT = re.compile(r"\A\s{0,3}[\'\"]?\s{0,3}[:=]")

_REQUIREMENTS_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "Pipfile",
    "setup.py",
)


def _iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", ".iris", "dist", "build"}
    for path in root.rglob("*"):
        if any(part in skip for part in path.parts):
            continue
        if path.suffix in {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml"}:
            if path.stat().st_size > 512_000:
                continue
            files.append(path)
    return files


def _is_test_file(path: Path) -> bool:
    """Test suites routinely embed sample field names/fixtures (fake ssns,
    demo passport.yaml content, etc.) to exercise detection logic itself —
    that sample data isn't evidence the workload actually handles it."""
    if any(part in {"tests", "test"} for part in path.parts):
        return True
    stem = path.stem
    return stem.startswith("test_") or stem.endswith("_test")


def _scan_imports(text: str) -> tuple[set[str], set[str]]:
    providers: set[str] = set()
    frameworks: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            lowered = stripped.lower()
            for needle, provider in _PROVIDER_IMPORTS.items():
                if needle in lowered:
                    providers.add(provider)
            for needle, fw in _FRAMEWORK_IMPORTS.items():
                if needle in lowered:
                    frameworks.add(fw)
    return providers, frameworks


def _scan_models(text: str) -> set[str]:
    models: set[str] = set()
    for pattern in _MODEL_PATTERNS:
        for match in pattern.findall(text):
            models.add(match.lower())
    return models


def _scan_data_categories(text: str) -> set[str]:
    categories: set[str] = set()
    for category, pattern in _DATA_CATEGORY_PATTERNS.items():
        if pattern.search(text):
            categories.add(category)
    return categories


def _scan_data_categories_in_source(text: str) -> set[str]:
    """Like `_scan_data_categories`, but for source files: only count a term
    that sits where a real field would (assignment, annotation, or dict/JSON
    key), not one that merely appears in prose, a docstring, or a keyword
    list describing the vocabulary."""
    categories: set[str] = set()
    for category, pattern in _DATA_CATEGORY_PATTERNS.items():
        for match in pattern.finditer(text):
            if _CODE_ASSIGNMENT_CONTEXT.match(text[match.end() : match.end() + 6]):
                categories.add(category)
                break
    return categories


def infer_provider_from_model(model: str) -> str | None:
    """Infer provider slug from a model identifier (shared by observability adapters)."""
    if not model:
        return None
    normalized = model.strip()
    for pattern, provider in _MODEL_PROVIDER_PREFIXES:
        if pattern.search(normalized):
            return provider
    return None


def infer_providers_from_models(models: list[str]) -> list[str]:
    """Return sorted unique providers inferred from model names."""
    providers: set[str] = set()
    for model in models:
        provider = infer_provider_from_model(model)
        if provider:
            providers.add(provider)
    return sorted(providers)


def scan_data_categories_from_text(text: str) -> list[str]:
    """Scan arbitrary metadata/tags text for sensitive data category hints."""
    return sorted(_scan_data_categories(text))


def _scan_requirements(root: Path) -> tuple[set[str], set[str]]:
    providers: set[str] = set()
    frameworks: set[str] = set()
    for name in _REQUIREMENTS_FILES:
        req_path = root / name
        if not req_path.exists():
            continue
        text = req_path.read_text(encoding="utf-8", errors="ignore").lower()
        for needle, provider in _PROVIDER_IMPORTS.items():
            if needle in text:
                providers.add(provider)
        for needle, fw in _FRAMEWORK_IMPORTS.items():
            if needle in text:
                frameworks.add(fw)
    return providers, frameworks


def detect_workload(path: str = ".") -> dict[str, Any]:
    """Static offline detection of workload profile attributes."""
    root = Path(path).resolve()
    providers: set[str] = set()
    frameworks: set[str] = set()
    models: set[str] = set()
    data_categories: set[str] = set()

    req_providers, req_frameworks = _scan_requirements(root)
    providers |= req_providers
    frameworks |= req_frameworks

    for file_path in _iter_source_files(root):
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        p, f = _scan_imports(text)
        providers |= p
        frameworks |= f
        models |= _scan_models(text)
        if not _is_test_file(file_path):
            data_categories |= _scan_data_categories_in_source(text)

    agent_hints = sum(1 for _ in root.rglob("passport.yaml"))
    autonomy = "assistive"
    if agent_hints >= 3:
        autonomy = "supervised"
    if agent_hints >= 6:
        autonomy = "autonomous"

    return {
        "source": "sdk_scan",
        "models": sorted(models),
        "providers": sorted(providers),
        "frameworks": sorted(frameworks),
        "data_categories": sorted(data_categories),
        "deployment_regions": ["us"],
        "agent_count": max(agent_hints, 1 if models or providers else 0),
        "autonomy_level": autonomy,
        "customer_facing": any(
            part in {"pages", "app", "frontend", "ui", "web"} for part in root.parts
        ),
    }


def profile_payload_hash(profile: dict[str, Any]) -> str:
    import hashlib

    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
