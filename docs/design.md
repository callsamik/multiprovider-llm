# multiprovider-llm — Design Spec (v1)

**Status:** v1 implemented — verified against this spec (Task 10, 2026-08-14)  
**Date:** 2026-08-14  
**Package:** `multiprovider-llm` (import: `multiprovider_llm`)  
**Scope:** Greenfield private library. No coupling to Autonomous Investment Navigator (AIN) in v1.

---

## 1. Goals

| Goal | Intent |
| :--- | :--- |
| **A. Maintainability** | Clear separation of multi-provider LLM connectivity from any application domain logic |
| **B. Private reuse** | Consumable from multiple projects via path/git dependency |
| **C. Eventual OSS** | Public-ready API and docs once the surface is proven; PyPI publish is **out of v1** |

**Non-goals (v1):** AIN integration, Groq/OpenRouter/Ollama presets, Redis (or other distributed) limiters, public PyPI release.

---

## 2. Approach

**Custom library** (not a thin façade over LiteLLM). Orchestration owns routing, freshness, retries, cooldowns, and budgets. Adapters own HTTP / provider translation.

Inspired by patterns proven in AIN Layer 21, but **not** extracted from or dependent on that codebase. Domain prompts, investment schemas, and product policy stay in callers.

---

## 3. Runtime requirements

| Dependency | Range | Notes |
| :--- | :--- | :--- |
| Python | `>=3.11,<4` | Matches modern typing / asyncio expectations |
| httpx | `>=0.27,<1` | Sync + async HTTP; no vendor SDKs required for v1 |

Optional vendor SDKs are **not** dependencies. Adapters use `httpx` so importing `multiprovider_llm` does not pull Anthropic/Google client libraries.

Before any future PyPI publish: re-verify that `multiprovider-llm` and import name `multiprovider_llm` remain available (checked 2026-08-14: both returned HTTP 404).

---

## 4. Public API (v1)

### 4.1 Call surface

Sync primary; async mirrors the same kwargs.

```python
from multiprovider_llm import Client, AsyncClient

result = client.complete(
    prompt="...",                    # or messages=[...]
    tier="standard",                 # "simple" | "standard" | "complex" | None
    provider_chain=None,             # if set, overrides tier routing entirely
    response_format="text",          # "text" | "json"
    json_schema=None,                # only valid when response_format="json"
    freshness_required=False,
    timeout_s=None,
    include_raw=False,
)

result = await async_client.acomplete(...)  # same kwargs
```

**Input normalization**

- Accept `prompt: str` **or** `messages: Sequence[Message | Mapping[str, Any]]` (exactly one required).
- Internally normalize to `list[Message]` (typed model / protocol). Mappings accepted for convenience.

**Validation**

- If `json_schema` is set and `response_format != "json"` → raise `ValidationError`.
- `json_schema` is a **hint** for providers that support constrained decoding; callers remain responsible for strict domain validation.

**Routing**

- If `provider_chain` is provided → use that order **as-is** (full override of tier routing).
- Else → start from configured enabled provider order; apply `tier_routing` for `tier` when present.
- If `freshness_required=True` → drop providers with `freshness_ok=False` before attempts.

### 4.2 Result types

```python
@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)  # provider-specific metrics

@dataclass(frozen=True)
class AttemptRecord:
    provider: str
    model: str | None
    ok: bool
    error_type: str | None
    status_code: int | None
    latency_ms: float
    message: str | None  # truncated / sanitized

@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    tier: str | None
    latency_ms: float
    usage: Usage
    attempts: tuple[AttemptRecord, ...]
    raw: Mapping[str, Any] | None  # only when include_raw=True
```

`CompletionResult.raw` is **off by default**. Provider payloads may contain sensitive data.

### 4.3 What the library owns vs callers

| Library | Caller (e.g. AIN later) |
| :--- | :--- |
| Auth / base URL resolution | Domain prompts |
| Model resolution by tier | Strict product schema validation |
| Fallback chain + tier routing | Business “skip brief” policy beyond `freshness_required` |
| Per-provider cooldown + budgets | Investment-specific coercion |
| Timeouts, typed errors, attempt log | |
| Light JSON object extraction when `response_format="json"` | |

---

## 5. Orchestration flow

1. Normalize messages; validate kwargs.
2. Resolve provider chain (override vs tier routing).
3. Apply freshness filter when required.
4. If no providers remain → raise **`NoEligibleProviders`** (distinct from all-failed).
5. For each provider:
   - Skip if cooldown active or limiter denies (after atomic reserve attempt).
   - Resolve model: tier map → provider default.
   - Call adapter (`complete` / `acomplete`).
   - On **retryable** failure: release/adjust reservation as needed, append `AttemptRecord`, continue chain.
   - On **non-retryable** failure: release reservation, raise immediately (do not continue).
   - On success: finalize usage against per-provider + global limiter; return `CompletionResult`.
6. If every attempted provider failed → raise **`AllProvidersFailed`** with `attempts`.

**Async:** native async HTTP via `httpx.AsyncClient`. Do **not** wrap the sync hot path in `asyncio.to_thread` for v1.

**Separation:** orchestration = routing, freshness, retries, cooldowns, budgets; adapters = provider HTTP translation only.

---

## 6. Retryability

| Condition | Behavior |
| :--- | :--- |
| Rate limit (429 / provider rate headers) | Continue chain; record cooldown when applicable |
| Timeouts | Continue chain |
| Connection failures | Continue chain |
| Selected 5xx (e.g. 500, 502, 503, 504) | Continue chain |
| Auth failures (401 / 403) | **Stop** immediately |
| Validation / bad request (400) attributable to caller payload | **Stop** immediately |
| Configuration errors (missing key, unknown provider in chain) | **Stop** immediately |

Exact 5xx allow-list is defined in code and covered by unit tests.

---

## 7. Limits and cooldowns

### 7.1 Limiter protocol (experimental)

```python
class Limiter(Protocol):
    def try_reserve(self, provider: str, *, tokens: int | None = None) -> Reservation: ...
    def finalize(self, reservation: Reservation, *, usage: Usage) -> None: ...
    def release(self, reservation: Reservation) -> None: ...
```

- **Atomic reserve** before the HTTP call (sync and async callers must be safe under concurrency).
- Success → `finalize` (adjust reservation to actual usage when known).
- Failure / skip after reserve → `release`.
- Default implementation: **in-memory** per-provider limits + optional **global budget**.
- State is **thread-safe and async-safe** (e.g. a single `threading.Lock` protecting shared counters; document that the default limiter is process-local).

Distributed backends (Redis, app-managed quotas) are out of v1 but the protocol allows injection later.

### 7.2 Cooldowns

Per-provider cooldown after rate limits (duration from headers when present, else config default). Cooldown state shares the same concurrency requirements as the limiter.

---

## 8. Provider adapters

### 8.1 Contract

```python
class ProviderAdapter(Protocol):
    name: str
    def complete(self, req: ProviderRequest) -> ProviderResponse: ...
    async def acomplete(self, req: ProviderRequest) -> ProviderResponse: ...
```

`ProviderRequest` fields include: `messages`, `model`, `timeout_s` (units unambiguous), `response_format`, optional `json_schema`, `include_raw`, `extras`.

**`extras`:** adapters **may ignore** unknown keys; adapters **must not** silently reinterpret keys that collide with common request fields (document reserved names).

`ProviderResponse`: `text`, `usage`, optional `raw` (only if requested), HTTP metadata (status, headers for limit parsing).

Error bodies returned upward are **always truncated and sanitized**. `raw` is never populated on error paths unless explicitly required for debugging hooks (v1: not on errors).

### 8.2 Registry

- Explicit registration via `register_provider(name, factory)`.
- Built-ins registered **lazily** (first `Client` init / first resolve) so `import multiprovider_llm` does not import every provider module.
- Validate provider names; **reject duplicate** registrations unless `replace=True` (or equivalent) is explicitly passed.

### 8.3 v1 adapter set

| Adapter module | Providers |
| :--- | :--- |
| `openai_compat.py` | OpenAI (v1). Groq / OpenRouter / Ollama later as config presets on the same adapter |
| `anthropic.py` | Anthropic Messages API |
| `gemini.py` | Google Gemini generateContent |

---

## 9. Configuration (experimental)

Load from dict or JSON file. Shape (provisional):

- `providers`: map of name → `enabled`, `freshness_ok`, `models` (`simple` / `standard` / `complex`), `rate_limits`, `base_url`, env key name for API key
- `tier_routing`: optional preferred order per tier
- `global_budget`: optional ceiling for the default in-memory limiter

API keys **only** from environment (never logged). Mark config schema **experimental** in README until exercised by tests.

---

## 10. Errors

| Type | When |
| :--- | :--- |
| `ValidationError` | Bad kwargs / message shape |
| `ConfigError` | Invalid or incomplete configuration |
| `ProviderError` | Single-provider HTTP/model failure (status, truncated body, headers) |
| `RateLimited` | Provider signaled rate limit (may also trigger cooldown) |
| `NoEligibleProviders` | Chain empty after filters / all disabled / none eligible — **no attempts made** |
| `AllProvidersFailed` | ≥1 attempt made; all failed with retryable (or exhausted) errors |

`NoEligibleProviders` and `AllProvidersFailed` are **distinct** typed errors.

---

## 11. Package layout

```text
multiprovider-llm/
  pyproject.toml
  README.md
  LICENSE
  docs/design.md          # this document
  src/multiprovider_llm/
    __init__.py
    types.py
    protocols.py          # Limiter, ProviderAdapter, hooks — keep separate from types
    client.py
    async_client.py
    config.py
    routing.py
    limits.py
    serialization.py      # JSON extraction / coercion boundaries
    errors.py
    providers/
      base.py
      registry.py
      openai_compat.py
      anthropic.py
      gemini.py
  tests/
  docs/
```

**Experimental (README-labeled until stabilized):** config schema, `Limiter` protocol, observability/hooks.

---

## 12. Testing strategy

1. **Unit (no network):** routing, validation, serialization, limiter reserve/finalize under threads + asyncio, retryability matrix, registry rules, `NoEligibleProviders` vs `AllProvidersFailed`.
2. **Adapter contract (httpx mock / respx):** request shape, auth, model resolution, usage parse, truncated errors, `raw` only when opted in.
3. **Orchestration integration (fake adapters):** fallback, stop-on-auth, attempt records.
4. **Live smoke (opt-in):** `@pytest.mark.live`; skipped without keys; **excluded from required CI**.

Dev tooling: pytest, pytest-asyncio, respx (or httpx MockTransport).

---

## 13. Bootstrap and packaging

- Private git repo at `/Users/callsamik/Projects/multiprovider-llm` (sibling to AIN).
- Build backend: hatchling (via `pyproject.toml`).
- License: MIT placeholder pending final OSS decision.
- AIN adoption: later, via path or git dependency — **not part of this repo’s v1 work**.

---

## 14. Implementation phases (planning only)

1. Types, errors, protocols, serialization helpers + tests  
2. Registry + openai_compat adapter + mocks  
3. Anthropic + Gemini adapters  
4. Routing + Client orchestration + limiter/cooldown  
5. AsyncClient  
6. Config loader + README examples  
7. Freeze experimental labels only after tests pass  

Detailed task breakdown belongs in an implementation plan (separate from this spec).

---

## 15. Decisions log

| Decision | Choice |
| :--- | :--- |
| Success criteria | A + B + C (phased) |
| Packaging | Separate private package from day one |
| Call style | Sync primary + native async twin |
| Rate limits | Per-provider + optional global budget; injectable Limiter |
| Stack | Custom adapters (Approach 1) |
| Name | `multiprovider-llm` / `multiprovider_llm` |
| Chain vs tier | Explicit `provider_chain` overrides tier routing |
| Timeout field | `timeout_s` |
| Eligible vs failed | Distinct `NoEligibleProviders` / `AllProvidersFailed` |
