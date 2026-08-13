# multiprovider-llm

Multi-provider LLM client with tier routing, fallback chains, and per-provider / global budgets.

**Import:** `multiprovider_llm`  
**Status:** Private library under design / early bootstrap. Not published to PyPI yet.

## Design

See [`docs/design.md`](docs/design.md) for the approved v1 design.

## Experimental

The following are **experimental** until covered by tests and explicitly unmarked:

- Config file / dict schema
- `Limiter` protocol and default in-memory implementation
- Observability / hooks interfaces

## Requirements

- Python `>=3.11,<4`
- `httpx>=0.27,<1`

## Usage (target API)

```python
from multiprovider_llm import Client

client = Client(config)  # load via experimental config helpers — see docs/design.md
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
pytest
```

Live provider tests are opt-in (`pytest -m live`) and are not required for CI.

## License

MIT (see `LICENSE`). Final OSS publish decision is separate from v1.
