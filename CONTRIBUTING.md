# Contributing to IRIS SDK

Thanks for considering a contribution. This repo holds the open-source,
Apache-2.0 packages that let a Python agent enforce Cedar policy
locally — no network call required.

## Scope

This repo is OSS by design: SDK packages, LLM-provider adapters
(OpenAI, Anthropic, LangChain, CrewAI, Gemini, Vertex AI, MCP, ...),
local scan/check, local Cedar enforcement, and the demo app.

Centralized policy management, hosted Evidence Vault, SSO/RBAC, and
org-wide compliance reporting are IRIS Cloud features and live in a
separate private repo — PRs adding those won't be a fit here. If
you're unsure which side of the line a change falls on, open an issue
first and ask before writing code.

## Development setup

```bash
git clone https://github.com/IRIS-Security/iris-sdk
cd iris-sdk
python -m venv .venv && source .venv/bin/activate
pip install -e packages/iris-python[dev]
# plus whichever adapter you're changing, e.g.:
pip install -e packages/iris-anthropic
```

## Running tests

```bash
pytest packages/iris-python/tests -v
```

Run tests the same way for any other package you touched:
`pytest packages/<package>/tests`.

## Code style

```bash
ruff check packages/iris-python
mypy packages/iris-python
```

## Submitting a change

1. Fork the repo and branch off `main`.
2. Make your change with tests.
3. `ruff check` and `pytest` must pass locally.
4. Open a PR — the IRIS Governance Action runs on your diff
   automatically (we dogfood our own product on every PR).
5. Describe **why**, not just what — link an issue if one exists.

Commit messages: `<type>(<scope>): <description>`, e.g.
`fix(anthropic): handle empty tool_use blocks`.

## Reporting bugs / requesting features

Use the issue templates. For security vulnerabilities, see
[SECURITY.md](SECURITY.md) — please don't file a public issue.

## License

By contributing, you agree your contribution is licensed under
Apache 2.0, the same license as this repository.
