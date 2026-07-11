# IRIS SDK

Policy-as-code for AI agents. This SDK lets any Python application —
using OpenAI, Anthropic, LangChain, CrewAI, Gemini, or a custom agent
framework — enforce Cedar-based governance policies locally, with
zero network calls required to get started.

Free and open source. Use it to compile, test, and enforce policies
against your own agents today.

## Quickstart

```bash
pip install iris-security-sdk
```

```python
from iris_sdk import IrisAgent
from iris_openai import wrap

agent = wrap(your_openai_client, policy="./policies/default.cedar")
# Policy decisions now enforced locally on every call
```

## Documentation

Developer docs (getting started, CLI reference, compliance guides):
**https://iris-security.github.io/iris-sdk/**

## Need more?

Centralized policy management across a team, hosted audit evidence
with tamper-evident retention, SSO, RBAC, and compliance reporting
for ISO 42001 / SOC 2 / NIST AI RMF? That's IRIS Cloud — see
[iris-security.io](https://iris-security.io) for the managed platform
built on this SDK.

## License

Apache 2.0 — see LICENSE.
