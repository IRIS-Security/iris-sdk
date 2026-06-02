# iris-gemini

Drop-in IRIS governance for the [Google GenAI Python SDK](https://github.com/googleapis/python-genai).

Replace one line:

```python
# client = google.genai.Client()
client = IrisGemini(passport=passport)
```

Every `client.models.generate_content()` and `generate_content_stream()` call is evaluated against Cedar policy, recorded in the Evidence Vault, and enforced per `IRIS_ENV` (warn in dev, block in production).

## Install

```bash
pip install iris-security-gemini
```

## Quickstart

See [examples/governed_gemini.py](examples/governed_gemini.py).

## Environment

| `IRIS_ENV`    | Behavior                                    |
|---------------|---------------------------------------------|
| `dev`         | Fail open - warnings to stderr, never block |
| `production`  | Fail closed - `IrisViolationError` on deny  |

Defaults to `dev` when unset.
