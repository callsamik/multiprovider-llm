# multiprovider-llm — Generic policy knobs (v1.1 proposed)

**Status:** Accepted — implemented in v1.1 (Tasks 1–3, 2026-08-15)  
**Date:** 2026-08-15  
**Package:** `multiprovider-llm`  
**Relates to:** [`design.md`](design.md) (v1 frozen contracts)

---

## 1. Goal

Keep the library **domain-agnostic** while adding a few **good-to-have, opt-in** orchestration policies that many callers need (including AIN), without embedding any product/business logic.

**Rule of thumb:** if a bank chatbot or CI bot would use it unchanged → library. If only one product cares → caller.

---

## 2. In scope (v1.1)

### 2.1 Terminal auth failure policy

| Item | Spec |
| :--- | :--- |
| Call kwarg | `on_auth_failure: Literal["stop", "continue"] = "stop"` on `Client.complete` / `AsyncClient.acomplete` |
| `"stop"` (default) | Current v1 behavior: 401/403 (and other non-retryable auth-class `ProviderError`s) abort the chain immediately |
| `"continue"` | Record `AttemptRecord`, release reservation, try next provider in the resolved chain |
| Auth detection | `ProviderError` / subclass with `status_code in {401, 403}` |
| Exhaustion | If every provider fails under `"continue"`, raise `AllProvidersFailed` with `attempts` (same as today) |

**Non-goals for this knob:** do not change 400 / `ConfigError` / `ValidationError` stop behavior in v1.1. Callers that want “continue on everything” keep their own loop.

### 2.2 Observability hooks (minimal protocol)

Experimental, optional injection on `Client` / `AsyncClient` construction:

```python
class CompletionHooks(Protocol):
    def on_attempt(self, record: AttemptRecord) -> None: ...
    def on_success(self, result: CompletionResult) -> None: ...
    def on_failure(self, error: BaseException, *, attempts: tuple[AttemptRecord, ...]) -> None: ...
```

- Default: no hooks (None).
- Hooks must not alter control flow; if a hook raises, the library **swallows** the exception and continues (document this; covered by a unit test).
- Does **not** replace `CompletionResult.attempts`.

### 2.3 Documentation taxonomy (README)

Clarify three tiers:

1. **Core** — adapters, routing, freshness filter, limiter protocol, cooldowns, attempt log  
2. **Opt-in policy** — `on_auth_failure`, hooks, named OpenAI-compat presets (later)  
3. **Caller-owned** — prompts, schemas, spend gates, durable quota files, product freshness rules beyond the boolean filter  

---

## 3. Explicitly out of v1.1

| Item | Why |
| :--- | :--- |
| Investment / news prompts & schemas | Domain |
| Disk-backed quota / cooldown files | App persistence |
| “Continue on all errors” as default | Surprising; breaks fail-fast auth |
| Streaming, vision, Redis limiter | Separate milestones |
| Forwarding `json_schema` on the wire | Separate; still validated locally |
| Groq/OpenRouter/Ollama builtins | Optional presets later; still doable via `OpenAICompatAdapter` + `adapters=` / `register_provider` today |

---

## 4. Compatibility

- Default `on_auth_failure="stop"` → **no behavior change** for existing callers.  
- Hooks default off → **no behavior change**.  
- Bump package note to `0.1.0a2` (or keep `0.1.0a1` + changelog) when shipping.

---

## 5. Tests (library)

- `on_auth_failure="stop"`: first provider 401 → raises; second never called  
- `on_auth_failure="continue"`: first 401 → second succeeds; attempts length 2  
- `on_auth_failure="continue"`: all 401 → `AllProvidersFailed`  
- Hook `on_attempt` / `on_success` invoked; if hook raises, completion still succeeds (library swallows)

---

## 6. Acceptance

- [x] Design approved  
- [x] Implemented + unit tests green  
- [x] README / `design.md` §6 retryability updated for the optional continue path  
- [x] No AIN imports or investment strings in library
