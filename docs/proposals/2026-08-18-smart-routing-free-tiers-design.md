# Design: Experimental smart routing (v0.2, architect-revised)

**Status:** Architect-revised 2026-08-21 — **M1–M3 ranking contract signed off**; **M4 implementation review APPROVED**; merge not authorized  
**Original draft:** 2026-08-18  
**Revision:** 2026-08-21 (principal architect)  
**Package:** `multiprovider-llm` (`0.1.0a1` freeze stands; this is an experimental layer)  
**Controlling ADR:** [`docs/decisions/2026-08-21-smart-routing-experimental-layer.md`](../decisions/2026-08-21-smart-routing-experimental-layer.md)  
**Ranking-contract sign-off:** [`docs/decisions/2026-08-21-m1-m3-ranking-contract-signoff.md`](../decisions/2026-08-21-m1-m3-ranking-contract-signoff.md)  
**M4 authorization:** [`docs/decisions/2026-08-21-m4-smartclient-authorization.md`](../decisions/2026-08-21-m4-smartclient-authorization.md)  
**Freeze (unchanged):** [`docs/decisions/2026-08-15-architecture-freeze-0.1.0.md`](../decisions/2026-08-15-architecture-freeze-0.1.0.md)  
**Handoff:** [`2026-08-21-smart-routing-session-handoff.md`](2026-08-21-smart-routing-session-handoff.md)

**Related (not reopened):**

- [v1.1 generic policy hooks](2026-08-15-generic-policy-hooks-design.md) — accepted; no redesign
- [Artifact-store extraction](2026-08-15-artifact-store-extraction-survey-and-design.md) — **cancelled**; smart routing does not resurrect it

**AIN integration (consumer — separate repo, do not duplicate here):**  
AIN `docs/superpowers/specs/2026-08-18-multiprovider-smart-routing-ain-integration.md`

**Reference system:** OmniRoute `auto` combo engine — cherry-picked *shape* only; not a dependency and not a heuristic dump.

---

## 0. Revision from the 2026-08-18 draft

The original draft is **not approved as written**. These changes are normative:

| Original draft | Revised v0.2 |
| :--- | :--- |
| `tier_fit` += boost if provider listed first in AIN `tier_routing[tier]` | **Removed (D9).** `tier_fit = catalog.tier_affinity[tier]` only |
| Catalog conceived as free-tier stacking (`FreeTierCatalog`, `api_key_free_v1.json`) | Generic **`ProviderCatalog`**: provider, model, adapter, auth, `cost_tier`, capabilities, `tier_affinity` |
| `monthly_tokens` readable as if it were remaining quota | Static documented characteristic only. Runtime quota = injected `QuotaReader` |
| `LibraryConfig.routing_mode` + `Client.complete(..., routing_mode=...)` + `SmartClient` | **`Client` always chain; `SmartClient` always smart.** No hidden dispatch in `Client.complete()` |
| Commit to ~40 API-key providers | Start **~25**; do not commit to 40 until evidence |
| M1–M7 as one roadmap | **M1–M3 only**, then architecture review before M4 |
| Optional caller-supplied routing prior | **No prior in v0.2** |
| Cost factor always in the weighted sum | Context-aware: omit constant factors (e.g. `cost_inv` under `free_only`) and renormalize |
| Health implied as historical | Explicit **process-local** rolling window from `AttemptRecord` |
| Error classifier as simplified OmniRoute port | HTTP/provider-contract set only; do not import body-string heuristic collections |

---

## 1. Executive summary

Do **not** reject smart routing. AIN has a real multi-provider path; the static chain has measurable inefficiency (retrying a 429'd Groq model on the next request; ignoring quota headroom).

Do **not** reopen the 0.1.0 architecture freeze. Smart routing is an **evidence-triggered experimental layer above frozen execution primitives**.

```text
                    AIN
                     │
        why / evidence / policy
                     │
                     ▼
          ┌──────────────────┐
          │ SmartClient      │  ← experimental v0.2 (M4, authorized; not implemented)
          │ pool · rank      │
          │ LKGP · lockout   │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │ Client / core    │  ← frozen 0.1.0
          │ adapters         │
          │ fallback         │
          │ limiter          │
          │ freshness filter │
          └──────────────────┘
```

**Backward compatibility:** `Client.complete()` retains current chain semantics unchanged. AIN keeps using `Client` until it explicitly constructs `SmartClient`.

---

## 2. Controlling principle

Library = **how** the call runs reliably.  
AIN = **why**, with what evidence, and what it may affect.

| AIN supplies (policy) | Library uses (execution) |
| :--- | :--- |
| `tier` | Catalog `tier_affinity[tier]` |
| `task_kind` | LKGP key `{tier}:{task_kind}` only |
| `freshness_required` | Exclude catalog entries with `freshness_ok=false` |
| `free_only` | Exclude `cost_tier != "free"` |
| `QuotaReader` / `CooldownReader` | Scoring + prefilter inputs |
| AIN disk cooldown | Authoritative across restarts |

AIN does **not** pass `tier_routing` into the library. AIN's existing chain remains the baseline via frozen `Client`.

---

## 3. Problem statement (caller-driven)

AIN routes live briefs through remote free-cost providers plus local Ollama for non-live tasks, using the library's **static ordered fallback**. Gaps that justify an experimental layer:

| Frozen 0.1.0 behavior | Cost to AIN |
| :--- | :--- |
| Static `provider_chain` / `tier_routing` | First configured provider tried even when another has more headroom |
| Provider-level fallback | Groq 429 on one model still leads with Groq on the next request |
| No ranked execution | Cannot prefer healthier / higher-quota targets |
| No last-known-good stickiness | Re-probes from the top of the chain every call |

AIN already owns prompts, FREE_ONLY policy, freshness hard-block, disk quotas/cooldowns, and investment gates. Those stay in AIN.

### Explicit non-goals (all versions unless a later ADR says otherwise)

- OAuth flows; coding-agent providers as primary backends
- Porting OmniRoute (90+ providers, 14 factors, bandit, gateway UI)
- OmniRoute as a dependency
- LLM-as-router, embedding routing, keyword intent, prompt-text routing
- Bandit / exploration / probabilistic promotion / model learning
- Redis / distributed rate limiting
- `json_schema` wire-forward
- Named Groq / OpenRouter / Ollama presets
- Artifact-store extraction
- PyPI publication

---

## 4. Architecture

### 4.1 Module layout (library) — M1–M3 land these; `smart_client.py` is M4

```text
multiprovider_llm/
├── client.py                    # frozen 0.1.0 — always chain
├── smart_client.py              # M4 (authorized; not implemented)
├── catalog/
│   ├── __init__.py
│   ├── provider_catalog.py      # load + validate
│   └── data/
│       └── providers_v1.json    # start ~25 entries
├── routing/
│   ├── pool.py                  # M1: build_candidate_pool()
│   ├── prefilter.py             # M2
│   ├── scoring.py               # M3
│   └── lkgp.py                  # M3
├── resilience/
│   ├── model_lockout.py         # M2 — process-local
│   └── error_classifier.py      # M2 — HTTP/provider-contract
└── protocols.py                 # QuotaReader, CooldownReader, optional HealthMetricsReader
```

### 4.2 Three phases (design; execute loop is M4)

```text
Phase 1 — BUILD POOL     catalog + credentials + free_only + freshness_ok
Phase 2 — RANK           quota, health, latency, tier_fit, cost + LKGP
Phase 3 — EXECUTE        ranked fallback, model lockout, error classifier
                         (specified now; wired in SmartClient at M4)
```

M1–M3 must produce a **clean candidate/ranking contract** (pool → ranked targets + diagnostics) that M4 can call without redesign.

**Signed off 2026-08-21** as the M4 *input* boundary. **M4 authorized** the same day ([authorization ADR](../decisions/2026-08-21-m4-smartclient-authorization.md)); the implementation slice is a later artifact.

- `Candidate` = executable target identity (adapter, `base_url`, `http_referer`, cost, affinity). **No `pool_key`.** Shared-quota identity stays in catalog data and is interpreted by `QuotaReader`.
- `RankedTarget` = ranking decision (`score`, `factors`, `rank`) keyed by `(provider, model)` only. Do not put adapter / base URL on it to save M4 a lookup.
- M4 join: `(provider, model)` → originating `Candidate` → adapter / URLs → execution.
- `RankedTarget.score` is **comparative**, not an absolute quality rating. One eligible candidate after constant-factor removal scores `0.0`; soak must not treat that as unhealthy.
- Frozen `Client` keeps `is_retryable`. Future `SmartClient` **must** use `classify_error`. They are not interchangeable.
- Frozen chain currently imports via `routing` package re-exports that also load ranking. Accept for now; decouple before or during M4 if the graph becomes consequential.

### 4.3 Routing selection (one mechanism, not three)

| Surface | Behavior |
| :--- | :--- |
| `Client` / `AsyncClient` | Always chain. Frozen 0.1.0. No `routing_mode` kwarg on `complete()`. |
| `SmartClient` | Always smart. Experimental. Not implemented until M4 is authorized. |
| Config construction hint | Later, if needed: `routing_mode=chain` → construct `Client`; `routing_mode=smart` → construct `SmartClient`. Must not become a second dispatch inside `Client.complete()`. |

AIN chooses which client object to construct.

---

## 5. Phase 1 — Provider catalog and candidate pool (M1)

### 5.1 Catalog is a static execution catalog

Not an authoritative economics database. Not a free-tier stacking engine. Drift is expected; the catalog describes **known/static characteristics**.

```python
@dataclass(frozen=True)
class ProviderCatalogEntry:
    provider: str
    model: str
    display_name: str
    adapter: Literal["gemini", "anthropic", "openai_compat"]
    auth: Literal["api_key", "none"]
    api_key_env: str | None
    base_url: str
    cost_tier: Literal["free", "paid"]
    capabilities: Mapping[str, object]  # opaque; v0.2 may be empty
    freshness_ok: bool
    tier_affinity: Mapping[str, float]  # simple/standard/complex → [0, 1]
    monthly_tokens: int | None          # documented steady budget; NOT runtime quota
    pool_key: str | None                # shared-quota dedupe (optional)
    http_referer: str | None
    enabled_by_default: bool
```

**`monthly_tokens`:** documentation of a published/static characteristic. Scoring and prefilter **must not** treat it as remaining quota. Remaining quota comes only from `QuotaReader`.

**`free_only`:** generic orchestration filter. A CI bot or personal assistant may pass it. The library applies `cost_tier == "free"`. It does not encode AIN's FREE_ONLY product policy.

**`freshness_ok` / `freshness_required`:** AIN owns whether a task needs fresh information and may prefilter providers. When the caller passes `freshness_required=True`, the library excludes catalog entries whose `freshness_ok` is false. The library does **not** decide that a task requires freshness.

### 5.2 Initial catalog size

Start at **~25 entries** across the provider families AIN already uses plus a small number of additional API-key OpenAI-compat endpoints. Do **not** commit to ~40 until soak evidence. No OAuth, no scrapers, no coding-agent endpoints.

Builtin catalog + optional `catalog_path` override (D2).

### 5.3 Pool construction

```python
def build_candidate_pool(
    catalog: ProviderCatalog,
    *,
    credentials: CredentialResolver,
    tier: str | None,
    free_only: bool,
    freshness_required: bool,
    enabled_providers: frozenset[str] | None = None,
) -> list[Candidate]:
```

1. Include iff credentials present OR `auth == "none"`.
2. If `free_only`: drop `cost_tier == "paid"`.
3. If `freshness_required`: drop `freshness_ok == False`.
4. If `enabled_providers` set: intersect.
5. Dedupe by `(provider, model)`.

Output candidates carry `(provider, model, adapter, base_url, cost_tier, tier_affinity, http_referer)`. They do not carry AIN routing order, `monthly_tokens`, or `pool_key`. `pool_key` remains catalog/quota-accounting data.

---

## 6. Phase 2 — Prefilter, score, LKGP (M2–M3)

### 6.1 Prefilter (M2) — hard exclusion before scoring

| Filter | Source |
| :--- | :--- |
| In-process model lockout | `ModelLockoutTracker` |
| Injected disk cooldown | `CooldownReader` (optional) |
| Injected quota hard cutoff | `QuotaReader` remaining % below `min_quota_pct` (default 5%) |
| Missing adapter | skip with audit note |

### 6.2 Scoring (M3)

Defaults (experimental — **do not tune before soak**):

| Factor | Weight | Source |
| :--- | ---: | :--- |
| `quota` | 0.30 | Injected `QuotaReader`; default 1.0 if unknown |
| `health` | 0.25 | Process-local rolling `AttemptRecord` window → `1 - error_rate` |
| `latency_inv` | 0.20 | Same window, p95 latency |
| `tier_fit` | 0.15 | `catalog.tier_affinity[tier]` **only** |
| `cost_inv` | 0.10 | Inverse of catalog `cost_tier` / unit cost |

**D9:** no AIN `tier_routing` boost. No generic caller-supplied prior in v0.2 either.

**Context-aware weights:** drop factors that are constant across the eligible set (e.g. `cost_inv = 1.0` for every candidate when `free_only=True`), then **renormalize** remaining weights to sum to 1.0. Do not leave a meaningless constant in the sum.

With a single eligible candidate every remaining factor is constant, so **score is `0.0`**. That is comparative ranking information, not a quality or health rating.

```python
def calculate_score(
    factors: ScoringFactors,
    weights: ScoringWeights,
    *,
    constant_factors: frozenset[str] = frozenset(),
) -> float:
    active = {k: w for k, w in weights.items() if k not in constant_factors}
    total = sum(active.values()) or 1.0
    return clamp01(sum((w / total) * getattr(factors, k) for k, w in active.items()))
```

Stable sort: score desc, then provider name asc.

### 6.3 Health / latency semantics (D4)

```text
AttemptRecord  →  process-local rolling metrics  →  health / latency_inv
```

There is no persistent metrics database in v0.2. Empty window → treat as unknown (factor default 1.0). Optional `HealthMetricsReader` injection may override; it is not required.

This matches the 0.1.0 freeze: the library may keep **process-local execution state** without Redis or durable storage.

### 6.4 LKGP — keep it boring

| Property | Value |
| :--- | :--- |
| Key | `{tier}:{task_kind}` |
| Storage | In-process dict |
| Promotion | If last-known-good is in the pool and within **10%** of the best score, promote to rank #1 |
| Success | Remember target |
| Failure | Forget target |

No bandit, exploration, probabilistic promotion, model learning, or prompt semantics.

### 6.5 Request-aware inputs (caller-owned)

The library **must not** parse prompt text or classify intent. AIN's `assess_request_complexity()` stays in AIN and arrives as `tier`.

Deferred (not v0.2): static `model × task_kind` fitness table; context-window pre-filter.

---

## 7. Resilience primitives (M2) — used by M4 later

### 7.1 Model lockout

- Process-local, `(provider, model)` scoped, deterministic, expiring
- No persistence in v0.2
- AIN disk cooldown remains authoritative across restarts via `CooldownReader`

This is the concrete reliability win over the static chain (429 on Groq/model → next request avoids that pair).

### 7.2 Error classifier — HTTP/provider-contract only

Useful initial set:

| Signal | `should_fallback` | `lock_model` |
| :--- | :---: | :---: |
| HTTP 429 | Yes | Yes |
| HTTP 502 / 503 / 504 / 529 | Yes | No |
| HTTP 500 | Yes | No |
| HTTP 401 / 403 | Per `on_auth_failure` | No |
| Timeout / connect | Yes | No |
| Quota exhausted (`insufficient_quota`, `credits_exhausted`) | Yes | Yes |
| Model unavailable (`model_not_found`, `model_not_supported`) | Yes | Yes (terminal for model) |
| JSON extraction `ValidationError` | Yes | No |
| HTTP 400 validation | **No** | No |

Do **not** import OmniRoute's growing body-string heuristic collection because it exists. Inspiration is allowed; a giant heuristic engine is not.

This classifier is **not** frozen `is_retryable`. Chain `Client` continues to use `is_retryable`. M4 `SmartClient` must consume `classify_error` for ranked fallback / lockout. JSON extraction `ValidationError` is a fallback condition here; it is not retryable on the frozen chain.

---

## 8. Protocols and diagnostics

```python
class QuotaReader(Protocol):
    def quota_remaining_pct(self, provider: str, model: str) -> float | None: ...

class CooldownReader(Protocol):
    def is_cooling(self, provider: str) -> bool: ...
    def remaining_seconds(self, provider: str) -> float: ...

class HealthMetricsReader(Protocol):  # optional override
    def error_rate(self, provider: str, model: str) -> float: ...
    def p95_latency_ms(self, provider: str, model: str) -> float: ...
```

M1–M3 should expose ranking diagnostics (pool size, filtered size, ranked targets, LKGP promoted) so M4 can attach them to results without AIN-specific hooks. AIN may use existing `CompletionHooks` for telemetry. No new AIN-specific hook protocol.

Diagnostics consumers must treat `RankedTarget.score` as comparative rank among the eligible set. `score == 0.0` is not “provider unhealthy.”

`json_schema` remains a local validation hint. Smart routing is not the vehicle for structured-output wire-forward.

---

## 9. `SmartClient` (M4 — implementation review APPROVED; merge not authorized)

Canonical slice: [`docs/superpowers/plans/2026-08-21-smart-routing-m4-slice.md`](../superpowers/plans/2026-08-21-smart-routing-m4-slice.md).

`SmartClient` **composes** frozen adapters; it does **not** subclass `Client` and does not call `Client.complete()`. Dispatch uses `Candidate.adapter`, not `get_provider(provider name)`.

```python
class SmartClient:  # do not merge ranking into Client
    def complete(self, ..., *, task_kind: str | None = None, free_only: bool = False) -> CompletionResult: ...
    def explain_last_route(self) -> RoutingDiagnostics | None: ...
```

---

## 10. Consumer notes (AIN)

Default stays `Client` / chain until soak (D6). When M5 is later authorized, AIN would:

- Construct `SmartClient` explicitly (or via a construction-only config hint)
- Inject `AinQuotaReader` / `AinCooldownReader`
- Pass `tier`, `task_kind`, `freshness_required`, `free_only`
- Keep `validate_tier_routing()` as **AIN chain policy**, not as a library scoring input

Feed analysis / offline Ollama paths need not change.

---

## 11. Testing (M1–M3)

| Area | Approach |
| :--- | :--- |
| Pool build | Catalog fixtures; credential / `free_only` / `freshness_required` matrix |
| Pre-filter | Lockout + injected cooldown mocks |
| Scoring | Deterministic factors → expected order; constant-factor omission under `free_only` |
| D9 | Tests must fail if AIN `tier_routing` (or any caller order prior) affects score |
| LKGP | Promote within 10%; clear on failure |
| Error classifier | Table-driven HTTP status + the small body set above |
| Freeze | Existing `test_client.py` green; `Client.complete` has no `routing_mode` |

---

## 12. Risks

| Risk | Mitigation |
| :--- | :--- |
| Catalog drift | Versioned static catalog; caller override path; do not treat as live economics |
| Dual cooldown confusion | AIN disk wins across restarts; inject `CooldownReader` |
| Scoring opacity | Ranking diagnostics on the candidate/rank contract; no bandit |
| Over-engineering vs 3-provider chain | M1–M3 review gate before `SmartClient`; chain remains default |
| AIN policy leak | D9 tests; generic catalog names; no `tier_routing` in library types |
| FREE_ONLY leak | Caller policy + catalog `cost_tier` filter + tests |

---

## 13. D1–D9 (resolved)

| ID | Outcome |
| :--- | :--- |
| **D1** SmartClient separate | Accept. Do not retrofit ranking into `Client.complete()`. |
| **D2** Catalog | Accept builtin + override. Generic `ProviderCatalog`, not AIN/free-tier semantics. |
| **D3** Lockout persistence | In-process only. |
| **D4** Health source | Library process-local rolling metrics; injectable override optional. |
| **D5** Catalog size | Start ~25; do not commit to 40 until evidence. |
| **D6** AIN smart default | Only after soak. |
| **D7** Circuit breaker | Defer. |
| **D8** Task fitness | Defer. Absolutely no prompt classification. |
| **D9** AIN `tier_routing` in scoring | **No.** Caller-supplied `tier` + library-owned catalog affinity only. |

---

## 14. Roadmap and authorization gate

| Milestone | Owner | This ADR |
| :--- | :--- | :--- |
| **M1** Catalog + candidate pool + credential/freshness/free filtering | Library | **Authorized** |
| **M2** Model lockout + error classifier + prefilter | Library | **Authorized** |
| **M3** Scoring + LKGP + `QuotaReader` protocol | Library | **Authorized** |
| **Architecture review** | Architect | **Complete 2026-08-21** — contract approved as M4 input boundary |
| **M4 authorization** | Architect | **YES 2026-08-21** |
| **M4** `SmartClient` + `explain_last_route` | Library | **Implementation review APPROVED** — merge not authorized |
| **M5** AIN bridge + readers + feature flag | AIN | Gated |
| **M6** Soak chain vs smart | Both | Gated |
| **M7** GA 0.2.0 | Both | Gated |

M1–M3 succeed if they produce a clean, generic candidate/ranking contract with diagnostics — without AIN types, without `tier_routing`, and without changing `Client`.

---

## 15. Soak criteria (M6, not yet authorized)

Recorded so later review does not invent new goals:

| Metric | Pass |
| :--- | :--- |
| Live brief success rate | ≥ chain baseline |
| Mean attempts per successful brief | ≤ chain |
| p95 brief latency | ≤ chain + 10% |
| `free_only` violations | 0 |
| Freshness violations (Ollama on live) | 0 |
| Rollback | AIN constructs `Client` again |

Weights stay experimental until this data exists.

---

## 16. Approval checklist

- [x] Boundary: library does not absorb AIN policy (D9)
- [x] Query-aware boundary: caller supplies `tier`; no prompt-text routing
- [x] Catalog is generic `ProviderCatalog`; start ~25
- [x] `monthly_tokens` is static, not runtime quota
- [x] `freshness_required` is a catalog `freshness_ok` filter only
- [x] Scoring weights experimental; constant factors omitted
- [x] Health is process-local rolling `AttemptRecord`
- [x] LKGP boring; bandit excluded
- [x] Model lockout in-process; AIN disk cooldown authoritative across restarts
- [x] Error classifier scoped to HTTP/provider-contract set
- [x] `json_schema` still deferred
- [x] `CompletionHooks` unchanged
- [x] Artifact-store remains cancelled
- [x] No `routing_mode` on `Client.complete()`
- [x] M1–M3 authorized; ranking contract signed off as M4 input boundary
- [x] M4 (`SmartClient`) authorized 2026-08-21 — invariants frozen; [slice defined](../superpowers/plans/2026-08-21-smart-routing-m4-slice.md); [implementation review APPROVED](../decisions/2026-08-21-m4-implementation-review.md)
- [x] 0.1.0 freeze not reopened
