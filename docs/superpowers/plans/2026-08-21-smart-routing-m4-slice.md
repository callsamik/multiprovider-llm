# Smart routing M4 Implementation Slice + Acceptance Gates

> **Status:** Slice defined 2026-08-21. **M4 implementation review APPROVED.** Merge / push / PR still not authorized.

**Goal:** Define exactly what `SmartClient` owns, how it consumes the signed-off M1–M3 contract, what it must not do, and the tests that must pass before M4 is complete.

**Architecture:** `SmartClient` is a new experimental class beside frozen `Client`. It builds a candidate pool, ranks it, joins `(provider, model)` → `Candidate` (+ catalog entry for auth), attempts adapters in ranked order, and uses `classify_error` for fallback/lockout. It does not subclass `Client` and does not call `Client.complete()`.

**Tech Stack:** Python `>=3.11,<4`; existing `httpx` adapters; pytest; package `multiprovider_llm`.

**Controlling docs:** [M4 authorization](../../decisions/2026-08-21-m4-smartclient-authorization.md) · [ranking-contract sign-off](../../decisions/2026-08-21-m1-m3-ranking-contract-signoff.md) · [experimental-layer ADR](../../decisions/2026-08-21-smart-routing-experimental-layer.md) · [design](../../proposals/2026-08-18-smart-routing-free-tiers-design.md) · [0.1.0 freeze](../../decisions/2026-08-15-architecture-freeze-0.1.0.md)

## Global Constraints

Copied from the authorization ADR; every later coding task inherits them.

- `SmartClient` uses `classify_error`. Never implement ranked fallback as `if is_retryable(error)`.
- `Client` continues using `is_retryable`. Do not modify `Client.complete()`.
- `Candidate` has no `pool_key`. Do not add it.
- Shared-quota identity stays in catalog data; `QuotaReader` interprets it (`quota_remaining_pct(provider, model)`).
- `RankedTarget.score == 0.0` is not a health signal. Ranking is comparative, not absolute quality.
- No `routing_mode` on `Client`, `AsyncClient`, or `LibraryConfig`.
- No AIN `tier_routing` in library scoring or `SmartClient`.
- `SmartClient` is the only newly opened implementation boundary. M5–M7 stay gated.
- Package version stays `0.1.0a1`. Do not add `SmartClient` to top-level `multiprovider_llm.__all__`.
- No merge, push, or PR is authorized by this slice.

---

## 1. M4 scope — what SmartClient is responsible for

`SmartClient` owns **ranked execution** for one completion call:

1. Load / hold a `ProviderCatalog` (builtin or path override already implemented).
2. Build a `Candidate` pool (`build_candidate_pool`) from credentials + `free_only` + `freshness_required` + optional `enabled_providers`.
3. Rank (`rank_candidates`) with injected readers, process-local lockout, LKGP, and health.
4. Join each `RankedTarget` to the originating `Candidate` by `(provider, model)`.
5. Resolve credentials from the **catalog entry** with the same key (`auth`, `api_key_env`) — not from `Candidate` (which has neither `api_key_env` nor `pool_key`).
6. Construct a `ProviderAdapter` from `Candidate.adapter` + `base_url` + optional `http_referer`. Catalog provider names (`groq`, `openrouter`, …) are **not** frozen `get_provider()` registry names.
7. Attempt targets in ranked order. One HTTP attempt per target per request (no same-target `is_retryable` loop).
8. On failure, `classify_error` → fallback and/or `ModelLockoutTracker.lock`.
9. Record `AttemptRecord`s, feed `RollingHealthMetrics` when the client owns the local window, fire `CompletionHooks`, update LKGP remember/forget.
10. Return frozen `CompletionResult`, or raise frozen `NoEligibleProviders` / `AllProvidersFailed` / `BudgetExceeded` / `ValidationError` (only when classifier says do not fallback).
11. Expose `explain_last_route() -> RoutingDiagnostics | None`.

`SmartClient` does **not** own: AIN policy, soak, defaulting production to smart, async surface, circuit breaker, prompt classification, or changing frozen chain behavior.

### Construction (locked)

Compose. **Do not subclass `Client`.** Subclassing would inherit `complete()` and `is_retryable`.

```python
class SmartClient:
    def __init__(
        self,
        catalog: ProviderCatalog | None = None,
        *,
        credentials: CredentialResolver | None = None,
        quota_reader: QuotaReader | None = None,
        cooldown_reader: CooldownReader | None = None,
        health_reader: HealthMetricsReader | None = None,
        lockout: ModelLockoutTracker | None = None,
        lkgp: LkgpStore | None = None,
        metrics: RollingHealthMetrics | None = None,
        limiter: Limiter | None = None,
        hooks: CompletionHooks | None = None,
        enabled_providers: frozenset[str] | None = None,
        catalog_path: str | Path | None = None,
    ) -> None: ...

    def complete(
        self,
        *,
        prompt: str | None = None,
        messages: Sequence[Message | Mapping[str, Any]] | None = None,
        tier: str | None = None,
        task_kind: str | None = None,
        free_only: bool = False,
        freshness_required: bool = False,
        response_format: Literal["text", "json"] = "text",
        json_schema: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
        include_raw: bool = False,
        max_tokens: int | None = None,
        on_auth_failure: Literal["stop", "continue"] = "stop",
    ) -> CompletionResult: ...

    def explain_last_route(self) -> RoutingDiagnostics | None: ...
```

Defaults: `load_catalog()` or `load_catalog(path=catalog_path)`; `EnvCredentialResolver()`; new process-local `ModelLockoutTracker`, `LkgpStore`, `RollingHealthMetrics`; default `InMemoryLimiter` keyed by **catalog provider name** with the same per-provider inflight default Client uses (32). `health_reader` None → use owned `RollingHealthMetrics` as the scoring reader.

**Forbidden kwargs on `complete`:** `provider_chain`, `routing_mode`.

**Import path:** `from multiprovider_llm.smart_client import SmartClient` (submodule only).

**Async:** out of M4. No `AsyncSmartClient`.

---

## 2. Execution flow

```text
complete(...)
  │
  ├─ normalize messages (reuse frozen serialization)
  ├─ pool = build_candidate_pool(catalog, credentials, tier, free_only,
  │                             freshness_required, enabled_providers)
  ├─ result = rank_candidates(pool, tier, task_kind, lockout, lkgp,
  │                           quota_reader, cooldown_reader, health_reader,
  │                           known_adapters)
  ├─ store diagnostics for explain_last_route
  │
  ├─ if result.ranked_targets is empty:
  │     raise NoEligibleProviders
  │
  ├─ index = {(c.provider, c.model): c for c in pool}
  │
  └─ for target in result.ranked_targets:
        candidate = index[(target.provider, target.model)]   # M4 join
        entry = catalog entry with same (provider, model)   # auth only; scan entries
        adapter = factory(candidate, entry)                  # not get_provider(name)
        limiter.try_reserve(candidate.provider)
        attempt adapter.complete(ProviderRequest(..., model=candidate.model))
        record AttemptRecord → hooks + local metrics
        │
        ├─ success (incl. json extract ok):
        │     lkgp.remember(tier, task_kind, provider, model)
        │     return CompletionResult  (score is not a field; do not copy it)
        │
        └─ failure:
              decision = classify_error(exc, on_auth_failure=...)
              if decision.lock_model:
                  lockout.lock(provider, model, decision.cooldown_s)
              lkgp.forget(key) if this pair was the remembered LKGP target
              if decision.should_fallback:
                  continue
              raise  (attach attempts)
     raise AllProvidersFailed
```

Prefilter is **inside** `rank_candidates` (already implemented). SmartClient does not re-implement lockout/cooldown/quota/missing-adapter filters.

### Locked execution rules

| Topic | Rule |
| :--- | :--- |
| Join | `(provider, model)` → `Candidate` for adapter / `base_url` / `http_referer`. Same key → `ProviderCatalogEntry` for `auth` / `api_key_env`. |
| Dispatch | Switch on `Candidate.adapter` (`gemini` / `anthropic` / `openai_compat`). Set `adapter.name = candidate.provider`. |
| Registry | Do **not** call `get_provider(candidate.provider)`. Frozen registry only knows `openai` / `anthropic` / `gemini`. |
| Same-target retry | **None.** One attempt per ranked target. Chain-style `is_retryable` loops stay in `Client`. |
| JSON `ValidationError` | Classifier fallbacks (`should_fallback=True`). Frozen `Client` still raises. This difference is required. |
| `score == 0.0` | Attempt the target if it is ranked #1 (or promoted). Do not skip as unhealthy. |
| Limiter `RateLimited` | Record attempt; continue to next target; do not model-lock (inflight budget ≠ HTTP 429). |
| `BudgetExceeded` | Raise; do not ranked-fallback. |
| `http_referer` | Experimental subclass or wrapper of `OpenAICompatAdapter` that adds the header. **Do not modify frozen adapter modules.** |
| Diagnostics | Last `RankingResult.diagnostics` only. Callers must not treat `score` as quality/health. |

---

## 3. Existing components consumed

| Component | Module | Role in M4 |
| :--- | :--- | :--- |
| `ProviderCatalog` / `load_catalog` | `catalog/provider_catalog.py` | Static entries; auth + `pool_key` stay here |
| `CredentialResolver` / `EnvCredentialResolver` | `catalog/credentials.py` | Pool membership (`has_key` only) |
| `Candidate` | `routing/types.py` | Execution identity; **no `pool_key`** |
| `RankedTarget` / `RankingResult` / `RoutingDiagnostics` | `routing/types.py` | Ranking decision + explain |
| `build_candidate_pool` | `routing/pool.py` | Phase 1 |
| `rank_candidates` | `routing/rank.py` | Phase 2 (includes prefilter + LKGP promote) |
| `QuotaReader` | `protocols.py` | Injected; maps `(provider, model)` using catalog data it owns |
| `CooldownReader` | `protocols.py` | Injected disk/app cooldown |
| `HealthMetricsReader` | `protocols.py` | Optional override |
| `ModelLockoutTracker` | `resilience/model_lockout.py` | Process-local `(provider, model)` lock |
| `classify_error` / `FallbackDecision` | `resilience/error_classifier.py` | Ranked fallback + lockout |
| `RollingHealthMetrics` | `routing/metrics.py` | Default health/latency window from `AttemptRecord` |
| `LkgpStore` | `routing/lkgp.py` | Remember / forget / 10% promote |
| Frozen adapters | `providers/*.py` | Constructed via experimental factory; not via Client |
| `Limiter` / `InMemoryLimiter` | `limits.py` | Inflight; keyed by `candidate.provider` |
| `CompletionHooks` | `protocols.py` | `on_attempt` / `on_success` / `on_failure` |
| `normalize_messages` / `extract_json_text` | `serialization.py` | Same as Client |
| Frozen errors + `CompletionResult` | `errors.py` / `types.py` | Unchanged shapes |

**Not consumed for fallback:** `is_retryable`, `is_auth_failure` (auth goes through `classify_error`), `resolve_chain`, `resolve_model`, `LibraryConfig.tier_routing`, `Client.complete`.

---

## 4. Explicit non-goals

- Modify `Client`, `AsyncClient`, `Client.complete`, or `AsyncClient.acomplete`.
- Add `routing_mode` anywhere.
- Put `pool_key`, `api_key_env`, or `monthly_tokens` on `Candidate` / `RankedTarget`.
- Feed AIN `tier_routing` (or any caller order prior) into scoring.
- Parse prompt text / classify intent.
- `AsyncSmartClient`.
- M5 AIN bridge, M6 soak, M7 GA, changing AIN’s default client (D6).
- Circuit breaker, bandit, Redis, TPM, named Groq/OR/Ollama presets.
- `json_schema` wire-forward (still local extract only).
- New AIN-specific hook protocol.
- Add experimental symbols to `multiprovider_llm.__all__`.
- Merge, push, PR, PyPI.
- Reopen M1–M3 types or scoring weights.

---

## 5. Acceptance gates

M4 is complete only if **all** of the following are true. Tests live primarily in `tests/test_smart_client.py` plus freeze-guard updates. Use fake adapters; no live network.

### Behavioral

1. **Happy path join:** Ranked order is the attempt order. Fake adapters prove `(provider, model)` join used `Candidate.adapter` / `base_url`, not `LibraryConfig` chain order.
2. **Classifier fallback:** First target raises HTTP 429 `ProviderError` → `classify_error` fallback → second target succeeds. `is_retryable` is not imported by `smart_client.py`.
3. **Lockout:** 429 with `lock_model` → `ModelLockoutTracker.is_locked` for that pair on the next `complete()`; pair is absent from the next ranking (prefilter).
4. **JSON extract:** `response_format="json"` + invalid JSON → classifier fallback to next target (must not raise like frozen Client).
5. **Auth:** `on_auth_failure="stop"` + 401 does not continue; `"continue"` does.
6. **Empty rank:** all filtered → `NoEligibleProviders`; `explain_last_route()` still returns diagnostics with `filter_notes`.
7. **Exhaustion:** all ranked attempts fail with fallback → `AllProvidersFailed` with attempts recorded.
8. **Single eligible `score == 0.0`:** still attempted; success returns `CompletionResult`. Test asserts the call happened, not that score is “healthy.”
9. **LKGP:** after success, next rank for same `{tier}:{task_kind}` promotes that pair when within 10%; failure of that pair forgets.
10. **`free_only` / `freshness_required`:** paid / `freshness_ok=False` never attempted.
11. **Hooks:** `on_attempt` for each try; `on_success` / `on_failure` accordingly.
12. **Health:** local metrics record attempts; a subsequent rank with two candidates can differ after a failure (no need to assert exact weights).
13. **`explain_last_route`:** returns last diagnostics; `None` before any `complete()`.

### Boundary / freeze

14. `Client.complete` / `AsyncClient.acomplete` / `LibraryConfig` still have no `routing_mode`.
15. `Client.py` source is unchanged in M4 (no import-path edit required; see §6).
16. `smart_client.py` contains no `is_retryable` and no `tier_routing` / `routing_mode` / `routing_prior`.
17. `Candidate` dataclass still has no `pool_key` field.
18. Experimental modules (catalog / routing / resilience / `smart_client.py`) still do not mention `tier_routing` except frozen `routing/chain.py`.
19. `SmartClient` is not in `multiprovider_llm.__all__`.
20. Existing non-live suite (`pytest -m "not live"`) stays green, including frozen `test_client.py`.
21. Replace `test_smart_client_module_does_not_exist` with gates 14–19. The old “file must not exist” assertion is retired **only when coding starts**.

### Out of M4 completeness

- Live soak vs chain (M6).
- AIN constructing `SmartClient` (M5).
- Async.

---

## 6. Hardening decision — routing import-path coupling

**Decision: address during M4. Do not reopen M1–M3.**

**Why it is consequential now:** M4 adds `smart_client.py`, which will import ranking heavily. Leaving `from .routing import resolve_chain` (used by frozen `Client`) as an eager import of `pool` / `rank` / scoring keeps the freeze-adjacent graph mixed. The ranking-contract review accepted this temporarily and deferred the split to “before or during M4 if consequential.” Adding the execution loop makes it consequential.

**How (tiny, no Client edit):**

- Change only `src/multiprovider_llm/routing/__init__.py`.
- Keep eager exports of **chain** symbols: `resolve_chain`, `resolve_model`, `is_retryable`, `is_auth_failure`.
- Lazy-export ranking symbols via module `__getattr__` (`rank_candidates`, `build_candidate_pool`, types, …), **or** stop re-exporting ranking from `__init__` and have SmartClient import `routing.rank` / `routing.pool` directly.
- Preferred: SmartClient imports submodules (`routing.rank`, `routing.pool`, `routing.types`) directly; `__init__.py` eagerly imports **only** `chain`. Ranking names may remain as `__getattr__` for compatibility with existing tests that do `from multiprovider_llm.routing import rank_candidates`.
- **Do not modify `client.py`.**

**Acceptance for this hardening:** a test that `importlib.import_module("multiprovider_llm.client")` does not leave `multiprovider_llm.routing.rank` in `sys.modules` after a clean import in a subprocess (or equivalent isolation). If a subprocess test is too heavy, asserting that `routing/__init__.py` does not contain `from .rank import` / `from .pool import` at module top level is the minimum static gate.

**Out of scope for the hardening:** moving files, renaming `routing/chain.py`, changing `is_retryable` behavior.

---

## File map (for the later coding start — do not create yet)

| Path | Responsibility |
| :--- | :--- |
| `src/multiprovider_llm/smart_client.py` | `SmartClient` — pool → rank → join → attempt → classify |
| `src/multiprovider_llm/routing/adapter_factory.py` | `adapter_for(candidate, *, api_key, http_referer)` from `Candidate.adapter` |
| `src/multiprovider_llm/routing/__init__.py` | Chain-only eager import + lazy ranking exports |
| `tests/test_smart_client.py` | Behavioral gates 1–13 |
| `tests/test_smart_routing_freeze.py` | Boundary gates 14–19 + import-graph hardening |
| `tests/test_routing_import_isolation.py` | Optional dedicated hardening test |

Do not create `async_smart_client.py`. Do not edit `client.py`, `async_client.py`, frozen `providers/*.py`, or `routing/types.py` except docstrings already signed off.

---

## Stop condition

M4 coding against this slice is **complete for review**. Merge / push / PR remains unauthorized.

```text
M4 AUTHORIZED
      ↓
SLICE + GATES  ✓
      ↓
smart_client.py  ✓  (review)
      ↓
gates 1–21  ✓  (pytest -m "not live": 158 passed)
      ↓
REVIEW RESULTS  ✓  APPROVED
      ↓
STOP
      ↓
merge / push / PR   ← separate authorization
M5–M7               ← gated
```
