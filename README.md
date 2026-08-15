# multiprovider-llm

Multi-provider LLM client with tier routing, fallback chains, and per-provider / global budgets.

**Import:** `multiprovider_llm`  
**Repo:** https://github.com/callsamik/multiprovider-llm  
**Status:** Public alpha (`0.1.0a1`). Not published to PyPI yet.

## Docs

| Doc | Purpose |
| :--- | :--- |
| **[Tutorial](docs/tutorial.md)** | How to use, configure, connect new agents, and write custom adapters |
| [Design](docs/design.md) | Approved v1 + v1.1 contracts |
| **[Architecture review pack](docs/architecture-review-pack-2026-08-15.md)** | As-built design for principal-architect critique (Q1–Q10) |
| [Plan](docs/plan.md) | Implementation task history |
| [Article](docs/medium-article.md) | Design and implementation write-up |
| [v1.1 policy knobs](docs/proposals/2026-08-15-generic-policy-hooks-design.md) | Accepted `on_auth_failure` + `CompletionHooks` |

## API surface

| Tier | What |
| :--- | :--- |
| **Core** | Adapters, routing, freshness filter, limiter protocol, cooldowns, attempt log |
| **Opt-in policy (v1.1)** | `on_auth_failure`, `CompletionHooks` on client construction |
| **Caller-owned** | Prompts, schemas, spend gates, durable quota files, product freshness rules beyond the boolean filter |

## Experimental

The following are **experimental** until covered by tests and explicitly unmarked:

- **Config file / dict schema** — shape may change; validated strictly (unknown top-level keys are rejected).
- **`Limiter` protocol** and the default in-memory implementation (`InMemoryLimiter`).
- **`CompletionHooks` protocol** — optional observability callbacks; hook exceptions are swallowed.

## Requirements

- Python `>=3.11,<4`
- `httpx>=0.27,<1`

## Install

```bash
pip install "git+https://github.com/callsamik/multiprovider-llm.git"
```

## Configuration

Set API keys in the environment (never in config files):

| Provider | Environment variable |
| :--- | :--- |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Gemini | `GEMINI_API_KEY` |

Reference JSON: [`examples/minimal_config.json`](examples/minimal_config.json).

`Client(config)` applies each builtin provider’s `base_url` and `api_key_env` from config. A missing or empty env value raises `ConfigError` before HTTP. Custom provider names still need `adapters=` or `register_provider` (see the [tutorial](docs/tutorial.md)).

```python
from multiprovider_llm import Client, load_config

config = load_config("examples/minimal_config.json")
client = Client(config)
result = client.complete(
    prompt="Summarize the input.",
    tier="standard",
    response_format="json",
    json_schema={"type": "object"},
    freshness_required=True,
)
print(result.provider, result.text)
```

Async: `AsyncClient.acomplete(...)` with the same parameters.

For Ollama / other OpenAI-compatible servers and **custom adapters**, see the
[tutorial](docs/tutorial.md) (§7–§8).

### v1.1 opt-in policy

**Auth failure policy** — by default, 401/403 abort the chain immediately. To fall through to the next provider:

```python
result = client.complete(prompt="...", on_auth_failure="continue")
```

**Observability hooks** — inject on construction; hooks observe only and do not replace `result.attempts`:

```python
class MyHooks:
    def on_attempt(self, record): ...
    def on_success(self, result): ...
    def on_failure(self, error, *, attempts): ...

client = Client(config, hooks=MyHooks())
```

### v1 accepted but explicitly deferred / not wired

- **`json_schema`**: Accepted and validated (`response_format` must be `"json"`). It is **not sent to providers** on the wire in v1. OpenAI-compatible adapters still set `response_format: json_object` when `response_format="json"`.
- **`max_tokens_per_minute`**: Parsed on `ProviderLimit` for forward-compatible config only. **Deferred — not enforced.** v1 limiter is **inflight concurrency only** (`max_inflight` + optional `global_budget`). Do not treat TPM as production-ready until a future version implements token-window accounting in `finalize` / `try_reserve`.

## Development

```bash
uv sync --dev   # or: pip install -e ".[dev]"
pytest -m "not live"
```

CI runs the same gate on push/PR (Python 3.11–3.13). The `@pytest.mark.live` marker is reserved for optional live provider smoke tests; **none ship in this repo yet**.

## License

MIT (see `LICENSE`).
