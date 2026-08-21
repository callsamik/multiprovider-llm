# ADR: M4 SmartClient implementation review

**Date:** 2026-08-21  
**Status:** Accepted  
**Verdict:** M4 implementation **APPROVED**  
**Does not authorize:** merge, push, PR, M5 (AIN), M6 (soak), M7 (GA)  
**Does not reopen:** [Architecture freeze 0.1.0](2026-08-15-architecture-freeze-0.1.0.md)  
**Parent:** [M4 authorization](2026-08-21-m4-smartclient-authorization.md)  
**Slice:** [`docs/superpowers/plans/2026-08-21-smart-routing-m4-slice.md`](../superpowers/plans/2026-08-21-smart-routing-m4-slice.md)  
**Branch:** `feat/smart-routing-m1-m3`

## Decision

The M4 `SmartClient` implementation satisfies the architecture gate and the frozen M4 slice (gates 1–21). Non-live suite: **158 passed**.

This is **not** merge authorization and does **not** open M5–M7.

```text
0.1.0 freeze        ✓
M1–M3               ✓
M3 contract review  ✓
M4 SmartClient      ✓ implementation + review
                     │
                     ▼
                  STOP
                     │
          merge / push / PR   ← separate authorization
          M5 AIN integration  ← gated
          M6 soak             ← gated
          M7 GA               ← gated
```

## Boundaries confirmed

| Boundary | Outcome |
| :--- | :--- |
| Frozen `Client` remains chain-only; no `Client.complete()` change | **Pass** |
| `SmartClient` is composition, not a subclass/modification of `Client` | **Pass** |
| Ranked order is execution order; config chain does not override it | **Pass** |
| Smart fallback uses `classify_error`; frozen Client keeps `is_retryable` | **Pass** |
| Lockout persists across `complete()` calls | **Pass** |
| JSON validation fallback is smart-routing only | **Pass** |
| AIN `tier_routing` stays out of experimental scoring | **Pass** |
| `Candidate` has no `pool_key` | **Pass** |
| Single-candidate `score == 0.0` remains executable | **Pass** |
| No AIN concepts in new modules | **Pass** |
| Frozen Client import path does not eagerly load ranking | **Pass** |
| `SmartClient` is not in package `__all__` | **Pass** |
| Regression suite | **158 passed** |

## Dispatch direction (approved)

```text
SmartClient
    ↓
adapter_factory
    ↓
Candidate.adapter
    ↓
frozen adapters
```

The factory belongs to experimental execution composition. Frozen adapter modules were not modified. Referer handling is an experimental subclass of `OpenAICompatAdapter`.

## Review table

| Area | Review |
| :--- | :--- |
| Frozen Client boundary | **Pass** |
| Candidate → ranked target → execution join | **Pass** |
| Smart fallback semantics | **Pass** |
| Lockout | **Pass** |
| LKGP | **Pass** |
| Freshness / `free_only` filtering | **Pass** |
| Auth policy | **Pass** |
| Diagnostics | **Pass** |
| Hooks | **Pass** |
| AIN boundary / D9 | **Pass** |
| Import isolation | **Pass** |
| Experimental API containment | **Pass** |
| Merge / push / PR | **Not authorized** |
| M5 / M6 / M7 | **Gated** |

## Consequences

- M4 code on this branch is the approved experimental execution layer.
- Do not merge, push, or open a PR from this review.
- Do not start AIN integration, soak, or GA work from this review.
- Chain remains the production default until a later soak decision (D6).
