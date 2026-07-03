# iris-langfuse

Read your existing [Langfuse](https://langfuse.com) project and derive an IRIS **WorkloadProfile** for compliance intelligence — without reimplementing tracing.

**Keep your Langfuse setup. IRIS reads what you're running and tells you which regulations apply — with tamper-evident proof.**

## Install

```bash
pip install "iris-langfuse[live]"
```

## Quickstart

```python
from iris_langfuse import profile_from_langfuse

profile = profile_from_langfuse(lookback_days=30)
print(profile["models"], profile["providers"])
```

Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and optionally `LANGFUSE_HOST`.

## Privacy

IRIS only reads trace **names, tags, and metadata** — never prompt or output content.

## IRIS Cloud bridge

```bash
export IRIS_API_KEY=your-token
python examples/governed_langfuse.py --push
```

Optional POST to `/intelligence/profile/scan` when `IRIS_API_KEY` is set.

## See also

- [Integrations docs](https://iris-security.github.io/iris-sdk/integrations.html)
- [Compliance Intelligence](https://iris-security.github.io/iris-sdk/compliance-intelligence.html)
