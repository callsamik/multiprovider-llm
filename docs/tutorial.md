# Tutorial: using multiprovider-llm

This guide walks through day-to-day usage, configuration, connecting new providers
(“AI agents” in the sense of LLM backends), and writing custom adapters.

**Companion docs**

- Design (contracts): [`design.md`](design.md)
- Implementation plan (history): [`plan.md`](plan.md)
- Example config: [`../examples/minimal_config.json`](../examples/minimal_config.json)

**v1 scope**

| Built-in | Adapter |
| :--- | :--- |
| `openai` | OpenAI Chat Completions (`OpenAICompatAdapter`) |
| `anthropic` | Anthropic Messages |
| `gemini` | Google Gemini `generateContent` |

OpenAI-compatible locals (Ollama, LM Studio, vLLM, Groq, OpenRouter, …) work by
**reusing** `OpenAICompatAdapter` with another `base_url` — you usually do **not**
need a new adapter class. Write a custom adapter only for a non-compatible API.

Config schema, `Limiter`, and hooks are **experimental**.

---

## 1. Install

```bash
# From GitHub (public)
pip install "git+https://github.com/callsamik/multiprovider-llm.git"

# Or editable clone
git clone https://github.com/callsamik/multiprovider-llm.git
cd multiprovider-llm
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Requirements: Python `>=3.11,<4`, `httpx>=0.27,<1`. No vendor SDKs required.

Set keys in the environment (never in config files):

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
```

---

## 2. Five-minute quickstart

```python
from multiprovider_llm import Client, load_config

config = load_config("examples/minimal_config.json")
client = Client(config)

result = client.complete(
    prompt="Say hello in one short sentence.",
    tier="standard",
)
print(result.provider, result.model)
print(result.text)
print(result.usage)
print(result.attempts)  # every try in the fallback chain
```

Async twin (same kwargs):

```python
import asyncio
from multiprovider_llm import AsyncClient, load_config

async def main() -> None:
    client = AsyncClient(load_config("examples/minimal_config.json"))
    result = await client.acomplete(prompt="Ping", tier="simple")
    print(result.text)

asyncio.run(main())
```

### Prompt vs messages

Provide **exactly one** of `prompt` or `messages`:

```python
# Convenience
client.complete(prompt="Summarize this.")

# Full chat
client.complete(
    messages=[
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "List three colors."},
    ]
)
```

Mappings are accepted; internally they become `Message(role=..., content=...)`.

### Text vs JSON

```python
# Free text
client.complete(prompt="...", response_format="text")

# JSON object expected (library extracts a JSON object from the model text)
client.complete(
    prompt="Return {\"ok\": true}",
    response_format="json",
    json_schema={"type": "object"},  # validated locally; NOT sent on the wire in v1
)
```

Rules:

- `json_schema` is only allowed when `response_format="json"` (else `ValidationError`).
- In v1, `json_schema` is **accepted but not forwarded** to providers. OpenAI-compat still sets `response_format: json_object` when format is `"json"`.
- Your app should still validate domain schemas after `result.text`.

### Result shape

```python
result.text          # model output (JSON string if response_format="json")
result.provider      # which backend won
result.model
result.tier
result.latency_ms
result.usage         # Usage(prompt_tokens, completion_tokens, total_tokens, extras)
result.attempts      # tuple[AttemptRecord, ...] — successes and failures
result.raw           # None unless include_raw=True (may contain sensitive data)
```

```python
result = client.complete(prompt="...", include_raw=True)
# result.raw is the last successful provider payload (debug only)
```

---

## 3. Configuration (experimental)

Load from a JSON file or a dict:

```python
from multiprovider_llm import config_from_dict, load_config

config = load_config("path/to/config.json")
# or
config = config_from_dict({ ... })
```

Unknown **top-level** keys raise `ConfigError`. Provider entries are also validated strictly.

### Full schema sketch

```json
{
  "providers": {
    "openai": {
      "enabled": true,
      "freshness_ok": true,
      "models": {
        "simple": "gpt-4o-mini",
        "standard": "gpt-4o",
        "complex": "gpt-4o"
      },
      "default_model": "gpt-4o-mini",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "rate_limits": {
        "max_inflight": 4,
        "max_tokens_per_minute": 100000
      }
    }
  },
  "provider_order": ["openai", "anthropic", "gemini"],
  "tier_routing": {
    "simple": ["openai", "gemini", "anthropic"],
    "standard": ["anthropic", "openai", "gemini"],
    "complex": ["anthropic", "openai", "gemini"]
  },
  "global_budget": 16
}
```

| Field | Meaning |
| :--- | :--- |
| `enabled` | Dropped from chains when `false` |
| `freshness_ok` | If `false`, skipped when `freshness_required=True` (use for local/stale-cutoff models) |
| `models` | Per-tier model ids (`simple` / `standard` / `complex`) |
| `default_model` | Used when tier has no entry |
| `base_url` | Documented endpoint for that provider (builtins use their own defaults in factories today; **inject adapters** when you need a custom URL — see §6–§7) |
| `api_key_env` | Name of the env var holding the key (never the key itself) |
| `rate_limits.max_inflight` | Enforced by default `InMemoryLimiter` |
| `rate_limits.max_tokens_per_minute` | Accepted in config; **not enforced** in v1 |
| `provider_order` | Default fallback order |
| `tier_routing` | Preferred lead order per tier (remainder keep relative order from `provider_order`) |
| `global_budget` | Optional process-wide inflight ceiling |

See [`examples/minimal_config.json`](../examples/minimal_config.json).

---

## 4. Routing, tiers, and freshness

### Default chain

1. Start from `provider_order` (enabled only).
2. If `tier` is set and `tier_routing[tier]` exists, preferred providers move to the front; others keep relative order.
3. If `freshness_required=True`, drop any provider with `freshness_ok=False`.

### Explicit override

```python
# Ignores tier_routing entirely — uses this order as-is (enabled/known only)
client.complete(
    prompt="...",
    provider_chain=["gemini", "openai"],
)
```

### Freshness

```python
# Live / current-info work: skip local or stale-cutoff backends
client.complete(prompt="...", freshness_required=True)

# Offline / non-fresh work: allow freshness_ok=false providers
client.complete(prompt="...", freshness_required=False)
```

Mark local models `freshness_ok: false` in config so they never answer “what’s happening right now” when you pass `freshness_required=True`.

---

## 5. Fallback, retries, and errors

Orchestration walks the chain:

| Outcome | Behavior |
| :--- | :--- |
| Rate limit / timeout / connect / selected 5xx | Continue to next provider |
| Auth (`401`/`403`), caller validation (`400`), `ConfigError` | **Stop** immediately |
| Global `BudgetExceeded` | **Stop** |
| Empty chain / all skipped (e.g. cooling) with no attempts | `NoEligibleProviders` |
| ≥1 attempt, all failed | `AllProvidersFailed` (inspect `.attempts`) |

```python
from multiprovider_llm import (
    AllProvidersFailed,
    BudgetExceeded,
    NoEligibleProviders,
    ProviderError,
    RateLimited,
    ValidationError,
)

try:
    result = client.complete(prompt="...")
except NoEligibleProviders:
    ...  # nothing was tried
except AllProvidersFailed as e:
    for a in e.attempts:
        print(a.provider, a.ok, a.status_code, a.error_type, a.message)
except BudgetExceeded:
    ...  # global inflight budget exhausted
except ProviderError as e:
    ...  # non-retryable single-provider failure (e.g. auth)
except ValidationError:
    ...  # bad call kwargs / message shape
```

`RateLimited` is a `ProviderError` subclass used inside the chain (continue) and by the limiter for per-provider caps.

---

## 6. Built-in providers

With **no** `adapters=` argument, `Client` resolves names via the lazy registry:

| Name | Env key (factory default) | Notes |
| :--- | :--- | :--- |
| `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1/chat/completions` |
| `anthropic` | `ANTHROPIC_API_KEY` | Messages API |
| `gemini` | `GEMINI_API_KEY` | `generateContent` |

Those factories currently use each adapter’s **default** `base_url`. Config `base_url` / `api_key_env` document intent and matter for your own wiring; for custom URLs, inject adapters (§7–§8).

---

## 7. Connect a new OpenAI-compatible agent (no new class)

Use this for **Ollama**, LM Studio, vLLM, Groq, OpenRouter, Azure OpenAI-compatible gateways, etc.

### Step A — Config entry

```python
from multiprovider_llm import Client, config_from_dict
from multiprovider_llm.providers.openai_compat import OpenAICompatAdapter

config = config_from_dict(
    {
        "providers": {
            "openai": {
                "enabled": True,
                "freshness_ok": True,
                "models": {"standard": "gpt-4o-mini"},
                "default_model": "gpt-4o-mini",
                "base_url": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "rate_limits": {"max_inflight": 4},
            },
            "ollama": {
                "enabled": True,
                "freshness_ok": False,
                "models": {
                    "simple": "qwen2.5:7b",
                    "standard": "qwen3:14b",
                    "complex": "qwen3:14b",
                },
                "default_model": "qwen3:14b",
                "base_url": "http://localhost:11434/v1",
                "api_key_env": "OLLAMA_API_KEY",
                "rate_limits": {"max_inflight": 1},
            },
        },
        "provider_order": ["openai", "ollama"],
        "tier_routing": {
            "simple": ["ollama", "openai"],
            "standard": ["openai", "ollama"],
            "complex": ["openai"],
        },
    }
)
```

Provider names must match `^[a-z][a-z0-9_]*$`.

### Step B — Inject the adapter

Config alone does **not** auto-build a custom-named OpenAI-compat instance. Pass `adapters=`:

```python
import os

client = Client(
    config,
    adapters={
        # Builtins can still be resolved from the registry if omitted from this map
        # — but if you pass adapters=, you must supply EVERY name you will call.
        "openai": OpenAICompatAdapter(
            name="openai",
            api_key=os.environ["OPENAI_API_KEY"],
            base_url="https://api.openai.com/v1",
        ),
        "ollama": OpenAICompatAdapter(
            name="ollama",
            api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),
            base_url="http://localhost:11434/v1",
        ),
    },
)

# Prefer remote when freshness matters
client.complete(prompt="Latest market headline?", freshness_required=True)

# Allow local when freshness does not matter
client.complete(prompt="Rewrite this paragraph.", tier="simple", freshness_required=False)
```

**Important:** if you pass `adapters=`, every provider in the resolved chain must be present in that map. Omitting `adapters=` uses the registry (builtins only: `openai`, `anthropic`, `gemini`).

### Alternative — `register_provider`

```python
import os
from multiprovider_llm.providers.registry import register_provider
from multiprovider_llm.providers.openai_compat import OpenAICompatAdapter

register_provider(
    "ollama",
    lambda: OpenAICompatAdapter(
        name="ollama",
        api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),
        base_url="http://localhost:11434/v1",
    ),
    replace=False,
)

# Now Client(config) without adapters= can resolve "ollama"
client = Client(config)
```

Use `replace=True` only when intentionally overriding a name.

---

## 8. Write a custom adapter

Required when the backend is **not** OpenAI Chat Completions / Anthropic Messages / Gemini `generateContent`.

### Contract

```python
from multiprovider_llm.types import ProviderRequest, ProviderResponse

class MyAdapter:
    name: str

    def complete(self, req: ProviderRequest) -> ProviderResponse:
        ...

    async def acomplete(self, req: ProviderRequest) -> ProviderResponse:
        ...
```

`ProviderRequest` fields:

| Field | Role |
| :--- | :--- |
| `messages` | `tuple[Message, ...]` |
| `model` | Resolved model id |
| `timeout_s` | Seconds (or `None`) |
| `response_format` | `"text"` \| `"json"` |
| `json_schema` | Optional hint (may ignore in v1) |
| `include_raw` | If `True`, attach provider JSON to `ProviderResponse.raw` |
| `extras` | Opaque map — **ignore unknown keys**; never reinterpret `model`, `messages`, `timeout_s`, `response_format`, `json_schema` |

`ProviderResponse`:

| Field | Role |
| :--- | :--- |
| `text` | Model text |
| `usage` | `Usage(...)` (tokens may be `None`) |
| `status_code` | HTTP status |
| `headers` | For `Retry-After` / limit parsing upstream |
| `raw` | Only if requested |

On HTTP errors, prefer raising `RateLimited` (429) or `ProviderError` with a **truncated** body (`<= 500` chars). Reuse helpers:

```python
from multiprovider_llm.providers.base import raise_for_status, truncate_body
```

### Minimal custom adapter (sync + async)

```python
from __future__ import annotations

from typing import Any, Mapping

import httpx

from multiprovider_llm.errors import ProviderError
from multiprovider_llm.providers.base import raise_for_status
from multiprovider_llm.types import ProviderRequest, ProviderResponse, Usage


class EchoHttpAdapter:
    """Toy adapter: POST JSON {prompt} → {text} at a custom gateway."""

    name: str

    def __init__(self, name: str, *, api_key: str, base_url: str) -> None:
        self.name = name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, req: ProviderRequest) -> dict[str, Any]:
        # Do not read reserved names from req.extras
        user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        return {"model": req.model, "prompt": user}

    def _parse(self, req: ProviderRequest, response: httpx.Response) -> ProviderResponse:
        raise_for_status(self.name, response)
        data: Mapping[str, Any] = response.json()
        text = str(data.get("text") or "")
        return ProviderResponse(
            text=text,
            usage=Usage(),
            status_code=response.status_code,
            headers=dict(response.headers),
            raw=dict(data) if req.include_raw else None,
        )

    def complete(self, req: ProviderRequest) -> ProviderResponse:
        with httpx.Client(timeout=req.timeout_s) as client:
            response = client.post(
                f"{self._base_url}/v1/generate",
                headers=self._headers(),
                json=self._payload(req),
            )
        return self._parse(req, response)

    async def acomplete(self, req: ProviderRequest) -> ProviderResponse:
        async with httpx.AsyncClient(timeout=req.timeout_s) as client:
            response = await client.post(
                f"{self._base_url}/v1/generate",
                headers=self._headers(),
                json=self._payload(req),
            )
        return self._parse(req, response)
```

### Wire it into a client

```python
import os
from multiprovider_llm import Client, config_from_dict

config = config_from_dict(
    {
        "providers": {
            "echo": {
                "enabled": True,
                "freshness_ok": True,
                "models": {"standard": "echo-1"},
                "default_model": "echo-1",
                "base_url": "https://echo.example.com",
                "api_key_env": "ECHO_API_KEY",
                "rate_limits": {"max_inflight": 2},
            }
        },
        "provider_order": ["echo"],
    }
)

client = Client(
    config,
    adapters={
        "echo": EchoHttpAdapter(
            "echo",
            api_key=os.environ["ECHO_API_KEY"],
            base_url="https://echo.example.com",
        )
    },
)
print(client.complete(prompt="hi", tier="standard").text)
```

Or register globally:

```python
from multiprovider_llm.providers.registry import register_provider

register_provider(
    "echo",
    lambda: EchoHttpAdapter(
        "echo",
        api_key=os.environ["ECHO_API_KEY"],
        base_url="https://echo.example.com",
    ),
)
client = Client(config)  # resolves "echo" from registry
```

### Checklist for a new agent

1. Choose a provider `name` (`^[a-z][a-z0-9_]*$`).
2. Add a `providers` block (`enabled`, `freshness_ok`, `models`, `default_model`, `base_url`, `api_key_env`, optional `rate_limits`).
3. Put the name in `provider_order` and, if used, every `tier_routing` array you care about.
4. Either:
   - **OpenAI-compatible** → `OpenAICompatAdapter(..., base_url=...)`, or
   - **Custom API** → implement `complete` / `acomplete`.
5. Inject via `adapters=` **or** `register_provider`.
6. Store secrets only in env vars named by `api_key_env`.
7. Set `freshness_ok=false` for local / frozen-cutoff models.
8. Add a small respx/httpx mock test for your adapter’s request shape and error mapping.

---

## 9. Limits and cooldowns (experimental)

Default limiter: process-local `InMemoryLimiter`.

- Per-provider `max_inflight` from config `rate_limits` (default `1` if omitted in the constructed default limiter path — prefer setting explicitly).
- Optional `global_budget` across providers.
- Atomic **reserve → finalize (success) / release (failure or cancel)**.
- HTTP `429` triggers a cooldown so that provider is skipped briefly on later calls.

Inject your own limiter later by implementing:

```python
try_reserve(provider, *, tokens=None) -> Reservation
finalize(reservation, *, usage: Usage) -> None
release(reservation) -> None
```

```python
from multiprovider_llm.limits import InMemoryLimiter, ProviderLimit
from multiprovider_llm import Client

limiter = InMemoryLimiter(
    per_provider={
        "openai": ProviderLimit(max_inflight=4),
        "ollama": ProviderLimit(max_inflight=1),
    },
    global_budget=8,
)
client = Client(config, limiter=limiter, adapters=...)
```

---

## 10. What stays in *your* application

The library is connectivity + routing. Keep domain logic outside:

| Library | Your app |
| :--- | :--- |
| HTTP / auth / model resolution | Domain prompts |
| Fallback + tiers + freshness flag | Product “skip AI” policy beyond freshness |
| Budgets / cooldowns | Strict business schema validation |
| Light JSON object extraction | Investment scores, prices, tax, gates, etc. |

---

## 11. Troubleshooting

| Symptom | Likely cause |
| :--- | :--- |
| `ConfigError: unknown provider` | Name not in registry and not in `adapters=` |
| `ConfigError: no adapter registered for provider` | Passed `adapters=` but omitted a chain member |
| `NoEligibleProviders` | All disabled, filtered by freshness, or cooling with no attempts |
| `AllProvidersFailed` | Every attempt failed (check `.attempts`) |
| `ValidationError` on `json_schema` | Used without `response_format="json"` |
| Local model used for “live” asks | Forgot `freshness_ok: false` or passed `freshness_required=False` |
| Custom `base_url` in JSON ignored | Builtin factory ignores config URL — inject `OpenAICompatAdapter` |
| Double-release warnings with custom limiter | Ensure `release` is idempotent (default limiter is) |

---

## 12. Next steps

- Read [`design.md`](design.md) for normative contracts.
- Copy [`examples/minimal_config.json`](../examples/minimal_config.json) and extend provider blocks.
- Prefer OpenAI-compat reuse before writing adapters.
- Before PyPI publish: re-check name availability and freeze the experimental config schema.
