# multiprovider-llm — Architecture Design Review Pack

**Audience:** Principal / staff architect (design modification review)  
**Status:** **Decided** — see [`decisions/2026-08-15-architecture-freeze-0.1.0.md`](decisions/2026-08-15-architecture-freeze-0.1.0.md) (Q1–Q10 accepted 2026-08-15). This pack remains the as-built critique input.  
**Date:** 2026-08-15  
**Package:** `multiprovider-llm` (import `multiprovider_llm`)  
**Version:** `0.1.0a1` public alpha  
**Normative contracts:** [`design.md`](design.md) (v1), [`proposals/2026-08-15-generic-policy-hooks-design.md`](proposals/2026-08-15-generic-policy-hooks-design.md) (v1.1), [architecture freeze ADR](decisions/2026-08-15-architecture-freeze-0.1.0.md)  
**Repo:** https://github.com/callsamik/multiprovider-llm  

This document restates the **as-built** architecture so a principal architect can critique boundaries, suggest modifications, and prioritize deferred work. **Decisions are recorded in the ADR**; where this pack and the ADR diverge, the ADR wins.

---

## 1. Executive summary

`multiprovider-llm` is a **domain-agnostic** Python library that owns:

1. Multi-provider **HTTP adapters** (OpenAI-compatible, Anthropic Messages, Gemini `generateContent`)
2. **Orchestration**: tier routing, explicit fallback chains, freshness filtering, retryability, process-local inflight limits, short cooldowns, attempt logging
3. **Typed results and errors** suitable for callers to audit without parsing vendor bodies

It deliberately does **not** own product prompts, investment schemas, durable disk quotas, spend gates, or “skip the feature” business policy.

**Primary consumer today:** Autonomous Investment Navigator (AIN) Layer 21, which wraps `Client.complete` behind a thin bridge (`complete_via_client` / adapter factory) and keeps all investment/news policy in AIN.

**Design stance:** custom library (not a LiteLLM façade). Orchestration and adapters are separated so callers can inject adapters and limiters without forking HTTP code.

---

## 2. Problem statement

Applications that call several LLM vendors need a repeatable answer to:

| Concern | Without a shared library | With this library |
| :--- | :--- | :--- |
| Vendor HTTP shapes differ | Copy-paste per app | Adapters behind one `ProviderAdapter` protocol |
| Failover / tier preference | Ad-hoc loops | `provider_chain` + `tier_routing` |
| “Local models are stale” | App-specific ifs | Config `freshness_ok` + `freshness_required` filter |
| Partial failure visibility | Log spaghetti | Immutable `AttemptRecord` on success and errors |
| Concurrency overload | Unbounded parallel calls | Injectable `Limiter` (default: per-provider + optional global inflight) |

AIN previously duplicated much of this in Layer 21. The library extracts the **connectivity and orchestration** slice so AIN (and future apps) share one tested surface.

---

## 3. Goals and non-goals

### 3.1 Goals

| ID | Goal |
| :--- | :--- |
| G1 | **Maintainability** — connectivity/orchestration separated from domain logic |
| G2 | **Private reuse** — path/git dependency across projects |
| G3 | **Eventual OSS readiness** — clean public API; PyPI publish still out of current alpha |

### 3.2 Non-goals (current)

| Non-goal | Rationale |
| :--- | :--- |
| AIN / investment domain logic | Belongs in the product |
| Built-in Groq / OpenRouter / Ollama *presets* as first-class named builtins | Same `OpenAICompatAdapter` + config/`adapters=` / `register_provider` today (AIN already wires them) |
| Distributed / Redis limiters | Protocol allows injection later |
| Streaming, vision, tool-calling as product features | Separate milestones |
| Enforcing TPM in the default limiter | **Resolved (ADR):** stripped from public config; concurrency-only default |
| Forwarding `json_schema` on the wire | Validated locally; wire-forward deferred |
| Durable disk quota / cooldown files | Caller-owned (AIN uses `data/ai_limits/`) |

---

## 4. Architecture overview

### 4.1 Layered view

```text
┌─────────────────────────────────────────────────────────────────┐
│ Caller (e.g. AIN Layer 21)                                      │
│  prompts · schemas · FREE_ONLY · disk quotas · product gates    │
└───────────────────────────────┬─────────────────────────────────┘
                                │ Client.complete / acomplete
┌───────────────────────────────▼─────────────────────────────────┐
│ Orchestration (client.py / async_client.py)                     │
│  normalize · validate · resolve_chain · freshness · reserve     │
│  retryability · cooldown · AttemptRecord · hooks (opt-in)       │
└───────────────┬─────────────────────────────┬───────────────────┘
                │                             │
        ┌───────▼───────┐             ┌───────▼───────┐
        │ routing.py    │             │ limits.py     │
        │ resolve_chain │             │ Limiter       │
        │ resolve_model │             │ CooldownTrack │
        │ is_retryable  │             │ (in-process)  │
        └───────┬───────┘             └───────────────┘
                │
        ┌───────▼───────────────────────────────────────┐
        │ ProviderAdapter protocol                       │
        │  openai_compat · anthropic · gemini · custom   │
        │  registry: lazy builtins + register_provider   │
        └───────────────────┬───────────────────────────┘
                            │ httpx
                    ┌───────▼───────┐
                    │ Vendor HTTP   │
                    └───────────────┘
```

### 4.2 Package layout (as-built)

```text
src/multiprovider_llm/
  __init__.py          # public exports + __version__
  types.py             # Message, Usage, AttemptRecord, CompletionResult, ProviderRequest/Response
  protocols.py         # ProviderAdapter, Limiter, Reservation, CompletionHooks
  client.py            # sync Client.complete
  async_client.py      # AsyncClient.acomplete (native async HTTP)
  config.py            # LibraryConfig, load_config / config_from_dict
  routing.py           # chain resolution, model resolution, retry/auth classification
  limits.py            # InMemoryLimiter, CooldownTracker, ProviderLimit
  serialization.py     # message normalize, light JSON extraction
  errors.py            # typed hierarchy
  providers/
    registry.py        # register_provider / get_provider (lazy builtins)
    openai_compat.py   # OpenAI + any OpenAI-compatible base_url
    anthropic.py
    gemini.py
    base.py
```

Approximate size at `dfe8f27`: ~1.7k LOC under `src/multiprovider_llm/`; **73** unit tests (no network in default CI).

### 4.3 Ownership split (hard rule)

| Concern | Library | Caller |
| :--- | :---: | :---: |
| HTTP translation / auth headers | ✓ | |
| Model pick by tier | ✓ | may override via config |
| Fallback order / tier reorder | ✓ | supplies config / `provider_chain` |
| Freshness boolean filter | ✓ | sets `freshness_ok` + `freshness_required` |
| Inflight concurrency (default) | ✓ | may inject `Limiter` |
| TPM / durable quotas |  | ✓ (caller-owned; library has no public TPM config) |
| Prompts / domain JSON schema |  | ✓ |
| Product “skip brief / FREE_ONLY” |  | ✓ |
| Disk cooldown files |  | ✓ (AIN); library has **in-process** cooldown only |

---

## 5. Public API surface

### 5.1 Construction

```python
from multiprovider_llm import Client, AsyncClient, load_config

config = load_config("config.json")  # or config_from_dict({...})
client = Client(config)                       # optional: hooks=, limiter=
async_client = AsyncClient(config, hooks=...)
```

- Builtins (`openai`, `anthropic`, `gemini`) auto-resolve from config `base_url` + `api_key_env` when `adapters=` is omitted.
- Custom names (e.g. `ollama`, `groq` as custom) require `adapters=` **or** `register_provider`.
- If `adapters=` is passed, the caller must supply **every** name that will be invoked (no silent merge of builtins into a partial map).

### 5.2 `complete` / `acomplete` kwargs

| Kwarg | Role |
| :--- | :--- |
| `prompt` **xor** `messages` | Input (normalized to `Message` list) |
| `tier` | `"simple" \| "standard" \| "complex" \| None` — drives model + optional reorder |
| `provider_chain` | If set, **full override** of tier routing order |
| `response_format` | `"text" \| "json"` |
| `json_schema` | Hint only when `response_format="json"`; **not sent on wire** today |
| `freshness_required` | Drop `freshness_ok=False` providers |
| `timeout_s` | Per-call timeout |
| `include_raw` | Attach vendor payload (off by default; may be sensitive) |
| `max_tokens` | Optional; Anthropic uses (default 1024) |
| `on_auth_failure` | `"stop"` (default) \| `"continue"` (v1.1) |

### 5.3 Results

Immutable dataclasses:

- `CompletionResult` — `text`, `provider`, `model`, `tier`, `latency_ms` (**wall-clock for whole orchestration**), `usage`, `attempts`, optional `raw`
- `AttemptRecord` — per try: provider, model, ok, error_type, status_code, latency_ms, truncated message
- `Usage` — prompt/completion/total tokens + `extras`

Stop-path and all-failed errors attach `attempts` when at least one attempt was recorded (`dfe8f27`).

### 5.4 Taxonomy (README)

1. **Core** — adapters, routing, freshness filter, limiter protocol, cooldowns, attempt log  
2. **Opt-in policy (v1.1)** — `on_auth_failure`, `CompletionHooks`  
3. **Caller-owned** — prompts, schemas, spend gates, durable quotas, product freshness beyond the boolean  

**Experimental (may change):** config file/dict schema, `Limiter` protocol + `InMemoryLimiter`, `CompletionHooks`.

---

## 6. Orchestration semantics (normative behavior)

```text
normalize + validate
    → resolve_chain (provider_chain XOR tier_routing over provider_order)
    → freshness filter
    → empty? raise NoEligibleProviders
    → for each provider:
          skip if cooldown active
          try_reserve (Limiter) — deny → skip / BudgetExceeded stop
          resolve_model(tier)
          adapter.complete / acomplete
          failure → release; append AttemptRecord; hooks.on_attempt
               retryable OR (auth && continue) → cooldown if rate limit; next
               else → raise with attempts (stop)
          success → finalize; hooks.on_success; return CompletionResult
    → AllProvidersFailed(attempts)
```

### 6.1 Retryability matrix

| Condition | Chain continues? |
| :--- | :---: |
| 429 / `RateLimited` | yes (+ cooldown) |
| Timeout / connect error | yes |
| 500, 502, 503, 504, 529 | yes |
| 401 / 403 | **no** by default; **yes** if `on_auth_failure="continue"` |
| 400 / validation attributable to payload | no |
| `ConfigError` / missing key mid-chain | no (after recording when applicable) |
| Global inflight `BudgetExceeded` | stop |

### 6.2 Sync vs async

- Sync: `httpx.Client` inside adapters / orchestration path.  
- Async: **native** `httpx.AsyncClient` — not `asyncio.to_thread` around sync.  
- Default limiter uses `threading.Lock` (process-local; async-safe under that lock).

---

## 7. Adapters and registry

### 7.1 Protocol

```python
class ProviderAdapter(Protocol):
    name: str
    def complete(self, req: ProviderRequest) -> ProviderResponse: ...
    async def acomplete(self, req: ProviderRequest) -> ProviderResponse: ...
```

Adapters own vendor URL/path, headers, JSON body shape, usage parsing, truncated error surfaces. They must not implement product routing.

### 7.2 Builtins vs OpenAI-compat reuse

| Module | Role |
| :--- | :--- |
| `openai_compat.py` | OpenAI Chat Completions; **also** Groq / OpenRouter / Ollama / vLLM when given the right `base_url` |
| `anthropic.py` | Messages API |
| `gemini.py` | `generateContent` |

**Architectural implication:** “support Ollama” does not require a new adapter class; it requires config + adapter injection (AIN does this). Builtin *presets* would only reduce boilerplate.

### 7.3 Registry

- `register_provider(name, factory, *, replace=False)`  
- Builtins registered **lazily** so `import multiprovider_llm` stays light  
- Duplicate registration rejected unless `replace=True`

---

## 8. Limits and cooldowns

### 8.1 Limiter protocol (experimental)

```python
try_reserve(provider, *, tokens=None) -> Reservation
finalize(reservation, *, usage) -> None
release(reservation) -> None
```

**Default `InMemoryLimiter`:**

- Enforces **`max_inflight` per provider**
- Optional **`global_budget`** (global inflight count)
- Accepts but **ignores** `usage` for accounting (default = inflight only; no public TPM config)
- Process-local only

### 8.2 Cooldowns

In-process per-provider cooldown after rate limits (`Retry-After` when present, else short default). **Not** durable across processes — AIN layers disk cooldowns on top for worker/MCP sharing.

### 8.3 Architect attention point

Config no longer advertises TPM-like fields. Default limiter = concurrency only. Token windows require an injected `Limiter` with an explicit contract (ADR Q3).

---

## 9. Configuration

Load from dict or JSON (experimental schema; unknown top-level keys rejected).

Typical shape:

- `providers[name]`: `enabled`, `freshness_ok`, `models{simple,standard,complex}`, `default_model`, `base_url`, `api_key_env`, `rate_limits`
- `provider_order`
- `tier_routing` (optional preferred order per tier; remainder keeps base relative order)
- `global_budget` (optional)

**Secrets:** environment only; never logged.

---

## 10. Error model

| Type | Meaning |
| :--- | :--- |
| `ValidationError` | Bad kwargs / message shape |
| `ConfigError` | Invalid / incomplete config or unknown chain name |
| `ProviderError` | Single-provider failure (status, truncated body, headers); may carry `attempts` |
| `RateLimited` | Rate / inflight denial |
| `BudgetExceeded` | Global inflight budget exhausted |
| `NoEligibleProviders` | Chain empty after filters — **zero** attempts |
| `AllProvidersFailed` | ≥1 attempt; all failed |

`NoEligibleProviders` vs `AllProvidersFailed` are intentionally distinct for caller metrics and UX.

---

## 11. Integration pattern (AIN — reference consumer)

AIN does **not** import library types into investment engines. Pattern:

```text
AIN build_provider / call_*
  → prefilter (AIN cooldown disk, freshness hard-block for live)
  → build_adapters() / get_adapter_for_provider()
  → complete_via_client(..., on_auth_failure="continue", response_format="json")
  → map CompletionResult → AiProviderResponse + AIN _record_limits
```

| Library default | AIN choice |
| :--- | :--- |
| `on_auth_failure="stop"` | `"continue"` (fallback parity) |
| Process cooldown | Plus disk `data/ai_limits/cooldowns.json` |
| Inflight only | Plus AIN spend caps / FREE_ONLY |
| No Ollama builtin | AIN registers OpenAI-compat Ollama `/v1` |

**Pin:** AIN `pyproject.toml` → `multiprovider-llm @ …@dfe8f27`.

This dual-layer limit story (library inflight + AIN disk/spend) is a deliberate boundary and a candidate for architect simplification later — without merging domain spend into the library.

---

## 12. Deferred / known gaps (review backlog)

| Item | Status | Notes |
| :--- | :--- | :--- |
| TPM / token-window limiter | Out until caller need | No public config; protocol `tokens`/`usage` retained for injection |
| `json_schema` wire-forward | Deferred | Local validation only |
| Named presets (Groq/OR/Ollama) | Optional later | Adapter already works |
| Streaming / tools / vision | Out | |
| Redis / distributed Limiter | Out | Protocol ready for injection |
| Live `@pytest.mark.live` suite | Reserved | Not required in CI |
| PyPI publish | Out of alpha | Name availability checked historically |
| Response headers on `AttemptRecord` | Gap | Callers (AIN) often record empty headers on Client success path |
| Per-call model override API | Gap | Callers rebuild config models or set tier maps (AIN uses `model_overrides` in bridge) |

---

## 13. Design tensions (questions for the principal architect)

These are the highest-leverage places to suggest modifications:

### Q1 — Boundary: how thin should the library stay?

**Today:** orchestration + adapters + process limits.  
**Alternative A:** even thinner — adapters only; every app owns failover.  
**Alternative B:** thicker — durable quotas, spend, schema validation in-library.  

*AIN vote so far: keep thin; product policy in AIN.*

### Q2 — Dual limit systems

Library inflight + AIN disk quotas/cooldowns overlap conceptually.  
**Options:** (1) keep dual (current), (2) pluggable durable `Limiter` implemented in AIN and injected, (3) move durable quotas into library (risks domain creep).

### Q3 — TPM honesty

**Options:** implement token window; strip TPM from config until ready; mark config keys `experimental` and fail-loud if set.

### Q4 — Builtin presets vs documentation

AIN already wires Groq/OpenRouter/Ollama. Should the library ship named factories to reduce adapter boilerplate, or keep “OpenAI-compat is enough”?

### Q5 — Auth default

Default `"stop"` is fail-fast and safer for multi-tenant bots. AIN needs `"continue"`. Is the default right for OSS, or should default be `"continue"` with docs warning?

### Q6 — `json_schema`

Keep as local hint forever, or prioritize wire-forward per provider (Gemini/OpenAI differ)?

### Q7 — Extending `AttemptRecord`

Add optional `headers` / `request_id` for audit parity with raw HTTP apps? Privacy tradeoff.

### Q8 — Versioning & stability

Alpha + experimental config/limiter/hooks. What should freeze for `0.1.0` vs stay experimental?

### Q9 — Async + limiter

Single process lock is fine for one worker. Multi-worker AIN deployments need either external limiter or documented “one Client per process + app quotas.” Is that acceptable?

### Q10 — Relationship to LiteLLM / vendor SDKs

Custom httpx adapters avoid SDK deps. Cost: maintenance of request shapes. Revisit if vendor APIs churn faster than expected.

---

## 14. Suggested review outcomes (decision template)

For each Q above, please mark:

| Decision | Modify now | Later | Accept as-is |
| :--- | :---: | :---: | :---: |
| … | | | |

Preferred artifacts after review:

1. Short ADR(s) in `docs/adr/` (or append to Decisions log in `design.md`)  
2. Updated experimental labels in README  
3. Ordered backlog for `0.1.0` / `0.2.0`

---

## 15. Quality and verification (current)

| Gate | Evidence |
| :--- | :--- |
| Unit tests | 73 passed @ `dfe8f27` (routing, limits, adapters mocked, client orchestration) |
| No vendor SDKs | httpx only |
| AIN soak | Phase 2 Client path + universal Ollama connector validated in AIN (separate repo) |
| Stop-path audit | `exc.attempts` recorded before raise (`dfe8f27`) |

---

## 16. Related documents

| Doc | Role |
| :--- | :--- |
| [`design.md`](design.md) | Frozen v1 design contract |
| [`proposals/2026-08-15-generic-policy-hooks-design.md`](proposals/2026-08-15-generic-policy-hooks-design.md) | v1.1 auth + hooks |
| [`tutorial.md`](tutorial.md) | Operator / integrator how-to |
| [`plan.md`](plan.md) | Historical implementation plan |
| [`medium-article.md`](medium-article.md) | Narrative write-up |
| AIN `docs/engines/news-ai-heal.md` §I5a | Consumer normative integration |

---

## 17. One-page cheat sheet

**Is:** multi-provider LLM client with routing, freshness filter, retry policy, process inflight limits, typed attempts.  
**Is not:** prompt framework, RAG, agent runtime, spend accounting, or investment logic.  
**Extend by:** `ProviderAdapter` + `register_provider` / `adapters=`; inject `Limiter` / `CompletionHooks`.  
**Do not put in library:** anything only one product would use unchanged.  
**Biggest honest caveat (resolved):** unenforced TPM config was stripped per ADR Q3. Remaining caveats are explicitly experimental surfaces (config / Limiter / hooks).
