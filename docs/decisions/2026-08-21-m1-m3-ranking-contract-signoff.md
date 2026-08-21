# ADR: M1–M3 candidate/ranking contract sign-off

**Date:** 2026-08-21  
**Status:** Accepted  
**M4 gate:** superseded by [M4 SmartClient authorization](2026-08-21-m4-smartclient-authorization.md)  
**Does not reopen:** [Architecture freeze 0.1.0](2026-08-15-architecture-freeze-0.1.0.md)  
**Parent ADR:** [Smart routing experimental layer](2026-08-21-smart-routing-experimental-layer.md)  
**Design:** [`docs/proposals/2026-08-18-smart-routing-free-tiers-design.md`](../proposals/2026-08-18-smart-routing-free-tiers-design.md)  
**Branch:** `feat/smart-routing-m1-m3`

## Decision summary

The M1–M3 candidate/ranking contract is **architecturally signed off as the M4 input boundary**.

**Follow-up (same date):** M4 was separately authorized in [`2026-08-21-m4-smartclient-authorization.md`](2026-08-21-m4-smartclient-authorization.md). Ranking-contract decisions in this ADR remain in force. This file is not an M4 plan and does not start coding.

```text
0.1.0 frozen
      │
      ▼
M1 ───✓  ProviderCatalog + candidate pool
M2 ───✓  lockout + classifier + prefilter
M3 ───✓  scoring + LKGP + QuotaReader
      │
      ▼
Candidate/ranking contract  APPROVED
      │
M4 authorization            YES (separate ADR; no code in that step)
      │
      ▼
M4 SmartClient              OPEN (slice not yet defined)
```

## Controlling distinction

`RankedTarget` is the **ranking decision**. `Candidate` is **execution configuration**. M4 joins them; it does not collapse them.

```text
(provider, model)
        ↓
Candidate
        ↓
adapter / base_url / http_referer
        ↓
execution
```

## Review items

| Item | Decision |
| :--- | :--- |
| `RankedTarget` is ranking-only (no adapter / base URL) | **Approved** |
| M4 join `(provider, model)` → `Candidate` | **Approved** |
| `pool_key` absent from `Candidate` | **Approved as-is** |
| `pool_key` interpreted by quota/accounting (`QuotaReader`) | **Approved** |
| Frozen `is_retryable` vs experimental `classify_error` coexist | **Approved** |
| M4 must use `classify_error`, not `is_retryable` | **Mandatory** |
| Single eligible candidate `score == 0.0` | **Approved** |
| Score is comparative ranking information, not absolute quality | **Mandatory interpretation** |
| Experimental ranking imported via `routing` package | **Accept now**; hardening later |
| Modify frozen `Client` | **No** |
| `routing_mode` on `Client.complete()` | **No** |
| AIN `tier_routing` in library scoring | **No** |
| `SmartClient` | **Authorized 2026-08-21** — see M4 authorization ADR |

## 1. RankedTarget vs Candidate

Keep them separate. Do not put adapter / `base_url` / `http_referer` on `RankedTarget` merely to save M4 a lookup.

- `Candidate` = executable target identity (adapter, URLs, cost tier, affinity).
- `RankedTarget` = ranking decision (`score`, `factors`, `rank`) keyed by `(provider, model)`.

## 2. `pool_key`

Keep out of `Candidate` for now.

`pool_key` describes **shared-quota identity**, not provider/model identity. Mapping `(provider, model) → pool_key` belongs in the quota/accounting layer (`QuotaReader` / catalog data), not the routing target.

Reopen only if ranking or diagnostics later need to *expose* shared-quota identity, with evidence.

## 3. Two retry policies

They answer different questions and are not interchangeable.

| Function | Owner | Meaning |
| :--- | :--- | :--- |
| `is_retryable(error)` | Frozen `Client` chain | 0.1.0 chain fallback semantics |
| `classify_error(error)` | Experimental smart routing | Fallback / lockout for ranked execution |

**Permanent M4 guard:** `SmartClient` uses `classify_error`. `Client` continues using `is_retryable`. M4 must not implement smart-routing fallback as `if is_retryable(error)`.

## 4. Score `0.0` for a single eligible candidate

This is the consequence of dropping constant factors and renormalizing remaining weights. With one candidate there are no differentiating factors, so `score = 0.0`.

**Invariant:** `RankedTarget.score` is **comparative ranking information**, not an absolute quality rating. Soak and diagnostics must not interpret `score == 0.0` as “provider is unhealthy.”

## 5. `routing` package import coupling

`from .routing import resolve_chain` currently loads experimental ranking as a side effect of frozen chain imports. The freeze constrains the `Client` contract, not the internal module layout. The current re-export is accepted because it preserves compatibility and freeze tests are green.

**Hardening (before or during M4, not a reopen of M1–M3):** make the frozen chain import path independent of experimental ranking modules (lazy export or package-boundary split). Desired direction:

```text
routing/chain.py  →  Client
routing/pool.py, prefilter.py, scoring.py, lkgp.py, rank.py  →  future SmartClient
```

## Consequences

- M1–M3 code on `feat/smart-routing-m1-m3` is the approved ranking contract.
- Ranking-contract decisions in this ADR remain in force after M4 authorization.
- Do not treat this ADR as a merge, publish, or coding start. M4 coding waits on a separate implementation slice.
