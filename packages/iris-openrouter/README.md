# IRIS OpenRouter

Compliance intelligence from [OpenRouter](https://openrouter.ai) usage
activity. IRIS reads which models you actually ran through OpenRouter, and
which providers served them, then tells you which regulations apply.

> **This is a live network call, not an offline check.** The adapter calls
> OpenRouter's `GET https://openrouter.ai/api/v1/activity` endpoint over the
> internet every time it runs. Nothing is cached or bundled locally.

## Requirements: a Management API key

`/api/v1/activity` only accepts an OpenRouter **Management API key**. That's
a different key from the one you use for chat completions, and
inference keys are rejected. Create a Management key at
[openrouter.ai/settings/management-keys](https://openrouter.ai/settings/management-keys);
see OpenRouter's [Management API Keys guide](https://openrouter.ai/docs/guides/overview/auth/management-api-keys).
For organizations, only Organization Admins can create one.

```bash
export OPENROUTER_MANAGEMENT_KEY=...
```

If the key is rejected (HTTP 401/403), or can't be a valid API key at all
(for example, it contains whitespace or a pasted `Bearer ` prefix), IRIS
stops and prints:

```
This looks like it might be a regular OpenRouter inference key. iris-openrouter needs a Management API key to read usage activity, these are different from the keys used for chat completions. Create one at: https://openrouter.ai/settings/management-keys
```

OpenRouter doesn't document a key prefix that distinguishes Management
keys from inference keys, so IRIS doesn't guess one from the key's format.
The key type is confirmed by OpenRouter's response.

## Install

Not yet published to PyPI. Install from the public repo:

```bash
pip install "git+https://github.com/IRIS-Security/iris-sdk.git#subdirectory=packages/iris-openrouter"
```

## Quickstart

```bash
iris compliance scan --from openrouter
```

Or from Python:

```python
from iris_openrouter import profile_from_openrouter

profile = profile_from_openrouter()  # reads OPENROUTER_MANAGEMENT_KEY
```

## Profile data IRIS derives

OpenRouter returns activity for the last 30 completed UTC days, grouped by
endpoint. From each row with at least one request, IRIS takes:

- **Models:** distinct `model` slugs, e.g. `openai/gpt-4.1`.
- **Providers:** distinct `provider_name` values, meaning the provider that
  actually served the request (e.g. `together` for a Llama model), which
  is where your data went.
- **Framework:** `openrouter`.

`summarize_activity(rows)` gives request and token volume per model and
provider. Volume isn't part of the WorkloadProfile shape, so it's reported
separately.

Not derived: OpenRouter activity has no prompt content, tool calls, agent
identity, or deployment region. Data categories stay empty,
`autonomy_level` stays `assistive`, `customer_facing` stays `false`,
`agent_count` is 1 when there is activity, and `deployment_regions` keeps
the same `us` default as the other IRIS adapters. Set these yourself if
you know them.

**What's read:** IRIS keeps only `date`, `model`, `model_permaslug`,
`endpoint_id`, `provider_name`, and the request/token counts. Cost fields
are dropped. The activity endpoint returns no prompt or completion
content.

## Push to IRIS Cloud (optional)

```bash
iris compliance scan --from openrouter --push
```

Requires `IRIS_API_KEY`. Pushing a one-time snapshot is free. Continuous
tracking and org-wide model exposure over time are IRIS Cloud features.

## License

Apache 2.0.
