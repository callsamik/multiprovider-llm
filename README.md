# multiprovider-llm

Multi-provider LLM client with tier routing, fallback chains, and per-provider / global budgets.

**Import:** `multiprovider_llm`  
**Repo:** https://github.com/callsamik/multiprovider-llm  
**Status:** Public alpha (`0.1.0a1`). Architecture frozen toward 0.1.0 — see [ADR](docs/decisions/2026-08-15-architecture-freeze-0.1.0.md). Not published to PyPI yet.

## Docs

| Doc | Purpose |
| :--- | :--- |
| **[Tutorial](docs/tutorial.md)** | How to use, configure, connect new agents, and write custom adapters |
| [Design](docs/design.md) | Approved v1 + v1.1 contracts |
| **[0.1.0 architecture freeze (ADR)](docs/decisions/2026-08-15-architecture-freeze-0.1.0.md)** | Q1–Q10 decisions — stop building unless a real caller needs it |
| **[Smart routing experimental layer (ADR)](docs/decisions/2026-08-21-smart-routing-experimental-layer.md)** | v0.2 approved in principle; M1–M3 signed off; M4 authorized |
| **[M1–M3 ranking-contract sign-off](docs/decisions/2026-08-21-m1-m3-ranking-contract-signoff.md)** | Contract approved as M4 input boundary |
| **[M4 SmartClient authorization](docs/decisions/2026-08-21-m4-smartclient-authorization.md)** | M4 yes; invariants frozen |
| **[M4 implementation review](docs/decisions/2026-08-21-m4-implementation-review.md)** | M4 code APPROVED; merge/M5–M7 not authorized |
| [Smart routing design](docs/proposals/2026-08-18-smart-routing-free-tiers-design.md) | Architect-revised catalog / ranking spec |
| [Smart routing session handoff](docs/proposals/2026-08-21-smart-routing-session-handoff.md) | Portable resume file for v0.2 work |
| [Architecture review pack](docs/architecture-review-pack-2026-08-15.md) | As-built critique input (superseded by the ADR for decisions) |
| [Plan](docs/plan.md) | Implementation task history |
| [Article](docs/medium-article.md) | Design and implementation write-up |
| [v1.1 policy knobs](docs/proposals/2026-08-15-generic-policy-hooks-design.md) | Accepted `on_auth_failure` + `CompletionHooks` |

## API surface

| Tier | What |
| :--- | :--- |
| **Frozen core** | Adapters, routing, fallback, freshness filter, retry classification, typed errors, attempt log, in-process cooldown, inflight concurrency |
| **Experimental** | Config schema, `Limiter` protocol / injection, `CompletionHooks`, call-site `on_auth_failure` |
| **Caller-owned** | Prompts, schemas, spend gates, durable quota files, product freshness rules beyond the boolean filter |

## Experimental

The following remain **experimental** (may change; do not treat as frozen 0.1.0 API):

- **Config file / dict schema** — shape may change; validated strictly (unknown keys are rejected).
- **`Limiter` protocol** and the default in-memory implementation (`InMemoryLimiter`).
- **`CompletionHooks` protocol** — optional observability callbacks; hook exceptions are swallowed.
- **`on_auth_failure`** — shipped opt-in policy knob; default remains `"stop"`.
- **Smart routing (v0.2, not shipped)** — generic `ProviderCatalog`, ranking, LKGP, model lockout as a separate `SmartClient`. Frozen `Client` stays chain-only. See the [2026-08-21 ADR](docs/decisions/2026-08-21-smart-routing-experimental-layer.md).

## Limits (honest contract)

The default limiter limits **concurrency**, not tokens:

- Enforced: per-provider `max_inflight` + optional process-wide `global_budget`.
- **Process-local:** one limiter instance controls one process. Multi-process deployments need caller-owned coordination.
- **Not in public config:** `max_tokens_per_minute` (rejected as unknown). Inject a custom `Limiter` if you need a token window.
- Protocol still accepts `try_reserve(..., tokens=)` and `finalize(..., usage=)` for injected limiters.

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
[tutorial](docs/tutorial.md) (§7–§8). OpenAI-compat is enough — there are no named Groq/OpenRouter/Ollama presets.

### v1.1 opt-in policy (experimental)

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

### Accepted but not wire-forwarded

- **`json_schema`**: Accepted and validated (`response_format` must be `"json"`). It is **not sent to providers** on the wire. OpenAI-compatible adapters still set `response_format: json_object` when `response_format="json"`. Provider-native structured output is deferred until a real caller needs it.

## Development

```bash
uv sync --dev   # or: pip install -e ".[dev]"
pytest -m "not live"
```

CI runs the same gate on push/PR (Python 3.11–3.13). The `@pytest.mark.live` marker is reserved for optional live provider smoke tests; **none ship in this repo yet**.

## License

MIT (see `LICENSE`).
