# Building multiprovider-llm: A Multi-LLM Client from Production Patterns

## Introduction

Over the past year, I've built the **Autonomous Investment Navigator** (AIN) — a Python-based research laboratory for evidence-driven investment discovery. A core challenge has been safely routing financial research prompts across multiple LLM providers with deterministic fallback logic, per-provider budgets, and cost control.

Patterns proven in AIN's Layer 21 inspired a greenfield library: **multiprovider-llm**, a standalone Python package (public alpha) that owns multi-provider LLM orchestration. v1 ships builtins for OpenAI, Anthropic, and Gemini; Groq, OpenRouter, and Ollama reuse the OpenAI-compatible adapter via config + registration.

This article walks through the design, implementation, and lessons learned.

---

## The Problem Space

### Why Multi-Provider?

Using a single LLM provider is comfortable but risky:
- **Vendor lock-in** — If OpenAI has an outage or changes pricing, your system breaks
- **Cost optimization** — Different providers suit different workloads (cheap for simple queries, capable for complex reasoning)
- **Latency resilience** — When primary provider is slow or rate-limited, fallback to secondary
- **Feature access** — Some capabilities (vision, structured output, extended context) vary by provider
- **Freshness requirements** — For real-time data validation, you need remote providers; local models have stale cutoffs

### The Complexity Tax

But multi-provider systems introduce unexpected complexity:

**API Surface Fragmentation**
- OpenAI: Chat Completions REST API with Bearer token
- Anthropic: Messages API with different error codes
- Gemini: generateContent with key in URL
- Each has its own model names, response format, token counting

**Rate Limiting & Budgets**
- Each provider reports rate limits differently (some via headers, some via status codes)
- You need per-provider inflight limits + global budgets
- Rate limit handling requires cooldown tracking and retry-after respect
- Concurrent callers need atomic reservation

**Deterministic Fallback Logic**
- Which providers to try, and in what order?
- How do you distinguish transient (retry) vs. terminal (stop) errors?
- What if auth fails on primary? (Don't try secondary, fail fast)
- What if timeout happens? (Retry, it's transient)
- Need attempt auditing for debugging

**Tier-Based Routing**
- "Simple" tasks → cheap models (gpt-4o-mini, llama-3.1-8b)
- "Complex" tasks → flagship models (gpt-4o, claude-3-5-sonnet)
- "Standard" → middle ground
- This routing logic compounds with provider selection

**Freshness Enforcement**
- Local models (Ollama, Qwen3) have training cutoffs; never use them for live news validation
- Only remote providers can validate current information
- This constraint must be enforced in orchestration, not left to callers

**Concurrency & Thread Safety**
- Multiple requests in flight to the same provider
- Atomic budget reservations
- Cooldown state shared across threads
- Most naive implementations aren't thread-safe

Attempting to handle all this ad-hoc in application code leads to:
- Scattered provider logic across the codebase
- Subtle bugs in fallback chains
- Rate limit surprises in production
- Inability to reason about system behavior

---

## Design Philosophy

Rather than wrap existing SDKs (OpenAI, Anthropic, google-generativeai) or adopt a heavy abstraction (LiteLLM), I chose to build a **custom, orchestration-first library**.

### Key Principles

- **Orchestration Owns Routing, Fallback, Limits, Budgets**
  - Client is the single source of truth for:
    - Which provider attempts happen, and in what order
    - When to stop (auth failure, no eligible providers)
    - When to continue (rate limit, timeout)
    - Attempt history and audit trail
  - Adapters are dumb: just HTTP translation

- **Protocol-Based, Not SDK-Based**
  - Define a clean adapter protocol: `complete(req) → response` and `acomplete(req) → response`
  - Implement adapters in pure httpx (no vendor SDKs as required dependencies)
  - This avoids:
    - SDK version conflicts
    - Unwanted transitive dependencies
    - SDK-specific retry/timeout semantics leaking into your logic

- **Config-Driven, Not Hard-Coded**
  - Provider order, models, rate limits, tier routing live in JSON
  - Swap strategies without redeploying code
  - Fail explicitly on invalid config (strict validation)

- **Deterministic Error Handling**
  - Define a retryability matrix: which exceptions should the library retry?
  - Stop on terminal errors (auth, validation, config)
  - Continue on transient errors (429, 5xx, timeout, connection)
  - Caller decides policy beyond that

- **Concurrency-Safe from Day One**
  - In-memory limiter with threading.Lock
  - Atomic reserve/finalize semantics
  - Ready for concurrent Client instances + async workloads
  - Distributed backends (Redis) pluggable via Limiter protocol

- **No Surprising Dependencies**
  - Only httpx (HTTP library)
  - Dev: pytest, pytest-asyncio, respx (mock HTTP)
  - Importing multiprovider_llm doesn't pull OpenAI SDK, Anthropic SDK, etc.

---

## Design Specification

Before implementing, I froze a detailed v1 design spec covering:

- Public API surface (Client.complete, AsyncClient.acomplete)
- Input validation and normalization
- Result types and attempt records
- Orchestration flow (resolve chain → reserve → attempt → release/finalize)
- Retryability matrix
- Limiter protocol (with default in-memory implementation)
- Cooldown semantics
- Provider adapter contract
- Error types
- Testing strategy
- Package layout

The spec is explicit about **what the library owns vs. what callers own**:

| Library | Caller |
|---------|--------|
| Auth / base URL resolution | Domain-specific prompts |
| Model resolution by tier | Strict product schema validation |
| Fallback chain + routing | Business policy (e.g., "skip brief if no Gemini") |
| Rate limits and budgets | Investment-specific coercion |
| Timeouts, typed errors, attempt log | |

This separation prevents scope creep and keeps the library focused.

---

## Implementation

### Architecture Layers

```text
                  ┌─────────────────────────┐
                  │  Client / AsyncClient   │
                  │   routing + fallback    │
                  └────────────┬────────────┘
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
             ▼                 ▼                 ▼
       ┌───────────┐     ┌───────────┐     ┌───────────┐
       │  Limits   │     │   Route   │     │  Errors   │
       └─────┬─────┘     └─────┬─────┘     └─────┬─────┘
             │                 │                 │
             └─────────────────┼─────────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │    Provider Registry    │
                  │      (lazy-loaded)      │
                  └────────────┬────────────┘
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
             ▼                 ▼                 ▼
      ┌─────────────┐    ┌───────────┐     ┌───────────┐
      │OpenAI Compat│    │  Claude   │     │  Gemini   │
      └─────────────┘    └───────────┘     └───────────┘
```

### Core Modules

**`types.py` — Frozen Data Models**
- `Message` (role, content)
- `CompletionResult` (text, provider, model, tier, latency_ms, usage, attempts, optional raw)
- `Usage` (prompt_tokens, completion_tokens, total_tokens, extras)
- `AttemptRecord` (provider, model, ok, error_type, status_code, latency_ms, message)

All frozen dataclasses for immutability and hashability.

**`client.py` — Sync Orchestration**
```python
def complete(
    prompt=None,
    messages=None,
    tier=None,                # "simple" | "standard" | "complex" | None
    provider_chain=None,      # explicit override of tier routing
    response_format="text",   # "text" | "json"
    json_schema=None,
    freshness_required=False,
    timeout_s=None,
    include_raw=False,
) → CompletionResult
```

Flow:
- Normalize messages (accept prompt OR messages, not both)
- Validate kwargs (json_schema requires response_format="json")
- Resolve provider chain (tier routing + freshness filter)
- If no providers eligible → raise `NoEligibleProviders` (don't attempt)
- For each provider in chain:
  - Skip if cooldown active
  - Try atomic reserve from limiter
  - If reserve fails → append AttemptRecord, continue
  - Build request (resolve model, handle response_format)
  - Call adapter
  - On success → finalize usage, return result
  - On retryable error → release, cooldown if 429, append AttemptRecord, continue
  - On terminal error → raise immediately (auth, validation, config)
- If all attempts fail → raise `AllProvidersFailed` with attempts

**`async_client.py` — Native Async**
- Mirrors Client.complete as acomplete
- Uses httpx.AsyncClient (not wrapped in to_thread)
- Same error handling, same return types

**`routing.py` — Chain Resolution**
```python
def resolve_chain(
    config,
    tier=None,
    provider_chain=None,
    freshness_required=False,
) → tuple[str, ...]
```

Logic:
- If explicit `provider_chain` provided → filter (enabled + freshness) and use it
- Else → start from `config.provider_order`, apply tier routing if tier is set
- Filter out disabled providers
- Filter out stale providers if `freshness_required=True`

**`limits.py` — Rate Limiting & Budgets**
```python
class InMemoryLimiter:
    def try_reserve(provider: str) → Reservation
    def finalize(reservation, usage: Usage) → None
    def release(reservation) → None
```

- Thread-safe with `threading.Lock`
- Per-provider inflight caps
- Global inflight budget
- `Limiter` is a protocol: easy to inject Redis later
- Cooldowns tracked separately (per-provider, duration from retry-after or config)

**`providers/` — Adapter Implementations**
Each adapter implements:
```python
class ProviderAdapter:
    name: str
    def complete(req: ProviderRequest) → ProviderResponse
    async def acomplete(req: ProviderRequest) → ProviderResponse
```

**OpenAI-Compatible** (openai_compat.py):
- Handles OpenAI, and can be reused for Groq, OpenRouter (both are OpenAI-compatible)
- Converts Message → Chat Completions format
- Parses usage from response
- Raises `RateLimited` on 429, `ProviderError` on other 4xx/5xx

**Anthropic** (anthropic.py):
- Messages API (not legacy Completions)
- Different auth header (x-api-key)
- Retryable overloaded responses (`529`) plus standard 5xx / `429`
- Different usage reporting; `max_tokens` from the request (default 1024)

**Gemini** (gemini.py):
- generateContent endpoint
- Key in URL query param, not header
- Converts Message → Content format (system text prefixed into the first user turn)

**`config.py` — Configuration**
```python
@dataclass
class ProviderConfig:
    name: str
    enabled: bool
    freshness_ok: bool
    models: dict[str, str]  # tier → model name
    default_model: str
    base_url: str
    api_key_env: str
    rate_limits: ProviderLimit | None

@dataclass
class LibraryConfig:
    providers: dict[str, ProviderConfig]
    provider_order: tuple[str, ...]
    tier_routing: dict[str, tuple[str, ...]]  # tier → preferred order
    global_budget: int | None
```

Validation:
- Unknown top-level keys are rejected (strict mode)
- Provider names in `provider_order` / `tier_routing` must exist in `providers`
- Runtime `provider_chain` unknown names raise `ConfigError`
- `Client(config)` applies each builtin’s `base_url` and `api_key_env` (missing keys fail fast)

**`errors.py` — Typed Exceptions**
- `ValidationError` (bad kwargs)
- `ConfigError` (invalid config)
- `ProviderError` (4xx/5xx, non-rate-limit)
- `RateLimited` (429, with headers for retry-after)
- `BudgetExceeded` (global inflight exceeded)
- `NoEligibleProviders` (no providers after filters)
- `AllProvidersFailed` (≥1 attempt, all failed retryably)

---

## Testing Strategy

Eleven test modules covering:

- **Unit Tests (no network)**
  - `test_routing.py` — chain resolution, tier routing, freshness filtering
  - `test_limits.py` — atomic reserve/finalize, per-provider vs. global, concurrency
  - `test_serialization.py` — message normalization, JSON extraction
  - `test_types.py` — dataclass construction, frozen semantics
  - `test_registry.py` — provider registration, lazy loading, deduplication

- **Adapter Contract Tests (respx mocks)**
  - `test_openai_compat.py` — request shape, auth header, model resolution, error parsing
  - `test_anthropic.py` — Messages API format, x-api-key header, `max_tokens`
  - `test_gemini.py` — generateContent format and message mapping

- **Integration Tests**
  - `test_client.py` — fallback, stop-on-auth, attempt records, budget exhaustion, config wiring
  - `test_async_client.py` — async fallback, same error handling
  - `test_config_load.py` — JSON parsing, validation

- **Live Smoke Tests**
  - `@pytest.mark.live` is reserved and excluded from CI; **no live modules ship yet**

Run:
```bash
pytest -m "not live"                 # required gate (also run in GitHub Actions)
pytest -v --tb=short tests/          # detailed output
```

---

## Usage Examples

### Basic Usage
```python
from multiprovider_llm import Client, load_config

config = load_config("config.json")
client = Client(config)

result = client.complete(
    prompt="Summarize the latest AI news",
    tier="standard",
)
print(f"Provider: {result.provider}")
print(f"Model: {result.model}")
print(f"Latency: {result.latency_ms:.0f}ms")
print(f"Answer: {result.text}")
```

### With Explicit Fallback Chain
```python
result = client.complete(
    prompt="Complex financial analysis",
    provider_chain=["openai", "anthropic", "gemini"],
    freshness_required=True,  # filter out stale local models
)
```

### Tier-Based Routing
```python
# Automatic model selection based on tier
result = client.complete(
    prompt="Is this a typo?",
    tier="simple",  # uses gpt-4o-mini, not gpt-4o
)
```

### JSON Response with Schema Hint
```python
result = client.complete(
    prompt="Extract: {news_item}",
    response_format="json",
    json_schema={
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "sentiment": {"type": "number"}
        }
    }
)
data = json.loads(result.text)
```

### Async
```python
async_result = await async_client.acomplete(
    prompt="...",
    tier="standard"
)
```

### Attempt Auditing
```python
result = client.complete(prompt="...", tier="standard")
for attempt in result.attempts:
    print(f"{attempt.provider}: {attempt.ok} in {attempt.latency_ms:.0f}ms")
# Output:
# openai: True in 523ms
# (or, if openai failed and gemini succeeded:)
# openai: False (rate limited) in 0ms
# gemini: True in 412ms
```

### Custom Limiter
```python
from multiprovider_llm import Client
from my_app import RedisLimiter

config = load_config("config.json")
limiter = RedisLimiter(redis_client)
client = Client(config, limiter=limiter)
```

---

## Lessons Learned

### Design-First Prevents Rework
Freezing the specification before implementation forced clarity:
- What does the library own?
- What does the caller own?
- When do we stop vs. retry?

This eliminated later scope creep and made implementation straightforward.

### Protocol-Based Beats SDK-Wrapping
Building on httpx + protocols proved cleaner than wrapping OpenAI/Anthropic SDKs:
- No transitive dependency bloat
- Full control over orchestration semantics
- Easy to add new providers without SDK updates
- Adapters stay simple (just HTTP translation)

### Concurrency-Safety Requires Atomic Ops
Early assumption: "Single-user MVP, thread safety can wait."
Reality: Build it in from the start. The overhead is minimal (a Lock around reservations), and bugs are hard to debug later.

### Config Validation Catches Mistakes Early
Strict config validation (rejecting unknown keys, validating provider references in tier_routing) caught configuration errors that would otherwise silently fail at runtime.

### Retryability Matrix Belongs in Docs
Documenting which errors are transient vs. terminal is as important as the code. Add a test for each cell of the matrix.

### Attempt Records Are Invaluable
Logging full attempt history (provider, model, latency, error type, status code) made production debugging and observability so much easier.

---

## What's Out of v1

Intentionally deferred:

- **Streaming** — Would require redesigning the result type (iterator vs. single value)
- **Vision / Multimodal** — Requires image input handling; adding later is feasible
- **Distributed Limiters** — Redis backend via Limiter protocol; low priority for single-user systems
- **Observability Hooks** — Not implemented in v1; use `CompletionResult.attempts`
- **Groq/OpenRouter Presets** — Reuse `OpenAICompatAdapter`; formal builtins wait for adoption feedback

Config schema and `Limiter` remain **experimental** in the README until stabilized by usage.

---

## Integration with Autonomous Investment Navigator

multiprovider-llm is **inspired by** AIN Layer 21 patterns, not a line-for-line extraction (AIN keeps domain prompts, schemas, and product policy). Future integration:

- **Adopt as sibling dependency**
  ```toml
  # pyproject.toml
  multiprovider-llm = { git = "https://github.com/callsamik/multiprovider-llm" }
  ```

- **Replace AiLiveAnalysisAgent.analyze()**
  - Current: direct calls to _call_openai, _call_gemini, etc.
  - Future: wrap Client.complete, inject audit logging

- **Inject Custom Limiter**
  - AIN already audits usage to disk (data/ai_limits/*.json)
  - Could inject limiter that logs to audit_path

- **Migrate Config**
  - Current: config/ai_providers.json (AIN-specific format)
  - Future: config/ai_providers.json (multiprovider_llm format)

Migration effort: ~2–4 hours, low-risk refactor.

---

## Future Roadmap

Post-v1 enhancements (subject to adoption feedback):

- **Streaming Support** — Iterator-based completion for long-running tasks
- **Observability Hooks** — Callbacks for attempt records, budget events
- **Distributed Limiters** — Redis backend; shared quota across processes
- **Groq/OpenRouter Presets** — Formal config entries when adopted
- **Vision Support** — Image input handling
- **PyPI Publication** — Once surface is proven; likely Q4 2026

---

## Getting Started

**GitHub:** https://github.com/callsamik/multiprovider-llm

**Clone and install:**
```bash
git clone https://github.com/callsamik/multiprovider-llm.git
cd multiprovider-llm
pip install -e ".[dev]"

# Run tests
pytest -m "not live"
```

**What's included:**
- Full design specification (docs/design.md)
- Tutorial + README with examples
- Eleven test modules + GitHub Actions CI
- Three adapters (OpenAI-compat, Anthropic, Gemini)
- MIT license

**Status:** v0.1.0a1 — public alpha; experimental surfaces labeled; suitable for early adoption with eyes open.

---

## Closing Thoughts

The multi-provider LLM routing problem is nuanced and easy to get wrong. Most solutions either:
- Wrap SDKs too tightly, losing visibility into orchestration
- Build abstractions too thin, leaving critical logic to callers
- Add too much magic, making failures hard to debug

multiprovider-llm aims for a third path: **lean orchestration, protocol-based adapters, and deterministic error handling**. The result is a library that's:
- Easy to reason about
- Safe for production (concurrency-safe, budget-controlled)
- Extensible (Limiter protocol, easy to add providers)
- Observable (full attempt history)

If you're building systems that use multiple LLM providers, give it a try and send feedback. If you're building the next big LLM application, I'd love to hear how you're solving this problem differently.

---

**Questions? Feedback? Contributions?**
- File an issue or PR on GitHub
- Reach out on LinkedIn or Twitter (@callsamik)
- Check docs/design.md for detailed specifications

Happy coding! 🚀