# iris-openai

Drop-in IRIS governance for the [OpenAI Python SDK](https://github.com/openai/openai-python).

Replace one line:

```python
# client = openai.OpenAI()
client = IrisOpenAI(passport=passport)
```

Every `client.chat.completions.create()`, `stream()`, and `client.embeddings.create()` call is evaluated against Cedar policy, recorded in the Evidence Vault, and enforced per `IRIS_ENV` (warn in dev, block in production).

Tool arrays are filtered to `passport.tool_permissions`; removed tools are logged as `IRIS-TOOL-001` (never silently dropped in dev).

## Install

```bash
pip install iris-openai
```

## Quickstart

See [examples/governed_gpt.py](examples/governed_gpt.py).

## Environment

| `IRIS_ENV`   | Behavior                                      |
|-------------|-----------------------------------------------|
| `dev`       | Fail open — warnings to stderr, never block   |
| `production`| Fail closed — `IrisViolationError` on deny    |

Defaults to `dev` when unset.
