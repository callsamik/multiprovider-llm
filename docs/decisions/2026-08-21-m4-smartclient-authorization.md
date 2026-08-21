# ADR: M4 SmartClient authorization

**Date:** 2026-08-21  
**Status:** Accepted  
**Authorizes:** M4 (`SmartClient`) as the only newly opened implementation boundary  
**Does not authorize:** M5+ (AIN bridge, soak, GA), merge, push, or PyPI  
**Does not reopen:** [Architecture freeze 0.1.0](2026-08-15-architecture-freeze-0.1.0.md)  
**Does not reopen:** M1–M3 ranking-contract decisions  
**Parent ADR:** [Smart routing experimental layer](2026-08-21-smart-routing-experimental-layer.md)  
**Ranking contract:** [M1–M3 ranking-contract sign-off](2026-08-21-m1-m3-ranking-contract-signoff.md)  
**Slice:** [`docs/superpowers/plans/2026-08-21-smart-routing-m4-slice.md`](../superpowers/plans/2026-08-21-smart-routing-m4-slice.md)  
**Implementation review:** [`2026-08-21-m4-implementation-review.md`](2026-08-21-m4-implementation-review.md)

## Decision

**Authorize M4 now.**

The approved M1–M3 candidate/ranking contract is sufficient to implement `SmartClient` without redesigning ranking, without modifying frozen `Client`, and without absorbing AIN policy.

```text
0.1.0 frozen
      │
      ▼
M1 ───✓
M2 ───✓
M3 ───✓
      │
Candidate/ranking contract  APPROVED
      │
M4 AUTHORIZATION            YES
      │
      ▼
M4 SmartClient              OPEN (implementation not started by this ADR)
```

This ADR does **not** start coding. The M4 implementation slice is [`docs/superpowers/plans/2026-08-21-smart-routing-m4-slice.md`](../superpowers/plans/2026-08-21-smart-routing-m4-slice.md). Coding waits on an explicit start.

## Sufficiency review (why yes)

M4 needs a generic ranked-execution loop. The signed-off contract already supplies it:

| M4 need | Provided by M1–M3 |
| :--- | :--- |
| Executable targets | `Candidate` (adapter, `base_url`, `http_referer`; **no `pool_key`**) |
| Ranked order + diagnostics | `rank_candidates` → `RankingResult` / `RankedTarget` |
| Join | `(provider, model)` → originating `Candidate` |
| Hard skips | prefilter (lockout, cooldown, quota cutoff, missing adapter) |
| Fallback / lockout signals | `classify_error` → `FallbackDecision` |
| Process-local lockout | `ModelLockoutTracker` |
| Health window | `RollingHealthMetrics` from `AttemptRecord` |
| Stickiness | `LkgpStore` remember / forget / promote |
| Quota / cooldown | injected `QuotaReader` / `CooldownReader` |

Frozen `Client` remains chain-only. Catalog `Candidate`s are not `LibraryConfig` chain entries; `SmartClient` must dispatch from `Candidate.adapter` + URLs, not by adding `routing_mode` to `Client.complete()`. That is an M4 wiring concern, not an M1–M3 contract hole.

Deferred import decoupling (`routing` package loading ranking as a side effect of chain imports) remains hardening **during** M4 if consequential. It does not block authorization and does not reopen M1–M3.

## Frozen M4 invariants

These are now binding for any M4 plan and implementation:

1. **`SmartClient` uses `classify_error`.** Ranked fallback and model lockout consume `FallbackDecision`. Do not implement smart fallback as `if is_retryable(error)`.
2. **`Client` continues using `is_retryable`.** Frozen chain semantics stay untouched.
3. **`Candidate` has no `pool_key`.** Adding it would reopen an approved decision and is out of scope.
4. **Shared-quota identity remains catalog data interpreted by `QuotaReader`.**
5. **`RankedTarget.score == 0.0` is not a health signal.** It is a comparative ranking outcome (including the single-eligible-candidate case).
6. **Ranking is comparative, not absolute quality.** Soak and `explain_last_route` must not treat score as a quality rating.
7. **No changes to frozen `Client`, `routing_mode`, or AIN `tier_routing` in library scoring.**
8. **`SmartClient` is the only newly opened implementation boundary.** Do not open M5 (AIN), M6 (soak), or M7 (GA) under this ADR.

## Still gated

| Milestone | Status |
| :--- | :--- |
| M4 implementation slice + acceptance gates | **Defined** — [`docs/superpowers/plans/2026-08-21-smart-routing-m4-slice.md`](../superpowers/plans/2026-08-21-smart-routing-m4-slice.md) |
| M4 coding (`smart_client.py`) | Permitted only after an **explicit coding start** |
| Merge / push / PR | Not authorized by this ADR |
| AIN defaulting to smart (D6) | Still after soak |
| Import-path decoupling | **Yes, during M4** — lazy ranking exports in `routing/__init__.py`; do not edit `client.py` |

## Consequences

- A later M4 plan must consume `rank_candidates` + `classify_error` + lockout + LKGP and join by `(provider, model)`.
- `SmartClient` may compose frozen adapters, limiter, hooks, and result types. It must not modify `Client.complete()`.
- Chain remains the production default until a later soak decision.
