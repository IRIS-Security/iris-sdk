# iris-litellm

Derive an IRIS **WorkloadProfile** from your [LiteLLM](https://github.com/BerriAI/litellm) deployment — static config or live proxy.

**Keep your LiteLLM router. IRIS reads what you're running and tells you which regulations apply — with tamper-evident proof.**

## Install

```bash
pip install "iris-litellm[live]"
```

## Quickstart — static config

```python
from iris_litellm import profile_from_litellm_config

profile = profile_from_litellm_config("./litellm.config.yaml")
```

## Quickstart — live proxy

```python
from iris_litellm import profile_from_litellm_proxy

profile = profile_from_litellm_proxy("https://litellm.internal", api_key="...")
```

## IRIS Cloud bridge

```bash
export IRIS_API_KEY=your-token
python examples/governed_litellm.py --config ./litellm.config.yaml --push
```

Optional POST to `/intelligence/profile/scan` when `IRIS_API_KEY` is set.

## See also

- [Integrations docs](https://iris-security.github.io/iris-sdk/integrations.html)
- [Compliance Intelligence](https://iris-security.github.io/iris-sdk/compliance-intelligence.html)
