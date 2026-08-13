# multiprovider-llm

Multi-provider LLM client with tier routing, fallback chains, and per-provider / global budgets.

**Import:** `multiprovider_llm`  
**Status:** Private library under design / early bootstrap. Not published to PyPI yet.

## Design

See [`docs/design.md`](docs/design.md) for the approved v1 design.

## Experimental

The following are **experimental** until covered by tests and explicitly unmarked:

- **Config file / dict schema** — shape may change; validated strictly (unknown top-level keys are rejected).
- **`Limiter` protocol** and the default in-memory implementation (`InMemoryLimiter`).
- **Observability / hooks** interfaces.

## Requirements

- Python `>=3.11,<4`
- `httpx>=0.27,<1`

## Configuration

Set API keys in the environment (never in config files):

| Provider | Environment variable |
| :--- | :--- |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Gemini | `GEMINI_API_KEY` |

Reference JSON: [`examples/minimal_config.json`](examples/minimal_config.json).

Load from a file or dict:

```python
from multiprovider_llm import Client, config_from_dict, load_config

# From JSON file
config = load_config("examples/minimal_config.json")

# Or build inline (same schema as the JSON example)
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
            },
        },
        "provider_order": ["openai"],
    }
)

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

## Development

```bash
uv sync --dev   # or: pip install -e ".[dev]"
pytest -m "not live"
```

Live provider tests are opt-in (`pytest -m live`) and are not required for CI.

## License

MIT (see `LICENSE`). Final OSS publish decision is separate from v1.
