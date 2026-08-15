# multiprovider-llm

Multi-provider LLM client with tier routing, fallback chains, and per-provider / global budgets.

**Import:** `multiprovider_llm`  
**Repo:** https://github.com/callsamik/multiprovider-llm  
**Status:** Public alpha (`0.1.0a1`). Not published to PyPI yet.

## Docs

| Doc | Purpose |
| :--- | :--- |
| **[Tutorial](docs/tutorial.md)** | How to use, configure, connect new agents, and write custom adapters |
| [Design](docs/design.md) | Approved v1 contracts |
| [Plan](docs/plan.md) | Implementation task history |
| [Article](docs/medium-article.md) | Design and implementation write-up |

## Experimental

The following are **experimental** until covered by tests and explicitly unmarked:

- **Config file / dict schema** — shape may change; validated strictly (unknown top-level keys are rejected).
- **`Limiter` protocol** and the default in-memory implementation (`InMemoryLimiter`).

**Out of v1 (not implemented):** observability / hooks APIs. Use `CompletionResult.attempts` for audit today.

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

### v1 accepted but not fully wired

- **`json_schema`**: Accepted and validated (`response_format` must be `"json"`). It is **not sent to providers** on the wire in v1. OpenAI-compatible adapters still set `response_format: json_object` when `response_format="json"`.
- **`max_tokens_per_minute`**: Accepted on provider `rate_limits` in config. **Not enforced** by `InMemoryLimiter` in v1 (only `max_inflight` and optional `global_budget` are).

## Development

```bash
uv sync --dev   # or: pip install -e ".[dev]"
pytest -m "not live"
```

CI runs the same gate on push/PR (Python 3.11–3.13). The `@pytest.mark.live` marker is reserved for optional live provider smoke tests; **none ship in this repo yet**.

## License

MIT (see `LICENSE`).
