# ADR: Architecture freeze toward 0.1.0

**Date:** 2026-08-15  
**Status:** Accepted  
**Context:** Principal review of [`architecture-review-pack-2026-08-15.md`](../architecture-review-pack-2026-08-15.md) (Q1–Q10) against as-built v1 + v1.1.

## Decision summary

Freeze the architecture. Make one honesty cleanup (strip unenforced TPM from public config). Leave everything else alone unless a real caller creates pressure.

## Q1–Q10

| Q | Decision | 0.1.0 action |
| :--- | :--- | :--- |
| Q1 Boundary | Keep thin (connectivity/orchestration only) | Freeze |
| Q2 Dual limits | Keep library process-local + caller durable quotas | Freeze |
| Q3 TPM honesty | Strip unenforced TPM from public config; do not implement TPM | **Modify** |
| Q4 Named presets | OpenAI-compat is enough; no Groq/OR/Ollama adapters or presets | Freeze |
| Q5 Auth default | Keep `on_auth_failure="stop"` | Freeze |
| Q6 `json_schema` wire-forward | Defer | Experimental / later |
| Q7 Attempt headers / request ID | Defer; prefer minimal `request_id` later if needed | Later |
| Q8 Versioning | Freeze core; keep config / Limiter / CompletionHooks experimental | Docs / labels |
| Q9 Async + limiter | Accept process-local semantics | Freeze + document |
| Q10 LiteLLM / vendor SDKs | Stay custom httpx adapters | Freeze; revisit on evidence |

## Frozen core (0.1.0 contract)

- `Client` / `AsyncClient`
- `Message` / `Usage` / `CompletionResult` / `AttemptRecord`
- `ProviderAdapter` + OpenAI-compat / Anthropic / Gemini adapters
- Routing, fallback, freshness filter, retry classification
- Typed errors
- In-process cooldown
- Inflight limiter semantics (concurrency, not tokens)
- Sync + async HTTP via httpx

## Explicitly experimental

- Config file / dict schema
- `Limiter` protocol and injected limiters (incl. default `InMemoryLimiter` as the reference)
- `CompletionHooks`
- Call-site `on_auth_failure` (shipped opt-in; not an architectural expansion)

## Not building (evidence-triggered only)

- Token-window / TPM limiter (and any public TPM config)
- `json_schema` wire-forward
- Named Groq / OpenRouter / Ollama presets
- Streaming / tools / vision
- Redis / distributed limiter
- PyPI publication

## Concrete change authorized by this ADR

Remove `max_tokens_per_minute` from public config and `ProviderLimit`. Unknown key → `ConfigError`.

Keep `Limiter.try_reserve(..., tokens=None)` and `finalize(..., usage=...)` so a future **injected** token-window limiter can use the protocol without advertising a non-functional default TPM feature.

## Process-local limiter (Q9)

One limiter instance controls **one process**. Multiple processes require caller-owned coordination. Durable quotas and cross-process cooldowns stay in the application (e.g. AIN).

## Consequences

- Next library change requires a real caller need, concrete failure, or evidence — not a roadmap item.
- Callers that previously passed `max_tokens_per_minute` in config must remove it (it never enforced anything).
- AIN pin / tests that construct `ProviderLimit(..., max_tokens_per_minute=...)` must be updated when bumping the library pin.

## Later evidence-triggered layer (does not reopen this freeze)

On 2026-08-21, AIN Layer 21 was accepted as real-caller evidence for an **experimental** smart-routing layer **above** this frozen core. Q1–Q10 and the frozen `Client` contract are unchanged. See [`2026-08-21-smart-routing-experimental-layer.md`](2026-08-21-smart-routing-experimental-layer.md). M1–M3 ranking contract signed off; M4 implementation review **APPROVED** ([review ADR](2026-08-21-m4-implementation-review.md)). Merge/push/PR and this freeze are unchanged.
