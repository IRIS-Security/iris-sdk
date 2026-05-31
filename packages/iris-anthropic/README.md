# iris-anthropic

Drop-in IRIS governance for the [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python).

Replace one line:

```python
# client = anthropic.Anthropic()
client = IrisAnthropic(passport=passport)
```

Every `client.messages.create()` and `client.messages.stream()` call is evaluated against Cedar policy, recorded in the Evidence Vault, and enforced per `IRIS_ENV` (warn in dev, block in production).

## Install

```bash
pip install iris-anthropic
```

## Quickstart

See [examples/governed_claude.py](examples/governed_claude.py).

## Environment

| `IRIS_ENV`   | Behavior                                      |
|-------------|-----------------------------------------------|
| `dev`       | Fail open — warnings to stderr, never block   |
| `production`| Fail closed — `IrisViolationError` on deny    |

Defaults to `dev` when unset.
