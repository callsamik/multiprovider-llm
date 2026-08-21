# ADR: Smart routing as an experimental v0.2 layer (narrowed)

**Date:** 2026-08-21  
**Status:** Accepted  
**Does not reopen:** [Architecture freeze 0.1.0](2026-08-15-architecture-freeze-0.1.0.md)  
**Canonical design:** [`docs/proposals/2026-08-18-smart-routing-free-tiers-design.md`](../proposals/2026-08-18-smart-routing-free-tiers-design.md) (architect-revised this date)  
**Handoff:** [`docs/proposals/2026-08-21-smart-routing-session-handoff.md`](../proposals/2026-08-21-smart-routing-session-handoff.md)  
**M1–M3 plan:** [`docs/superpowers/plans/2026-08-21-smart-routing-m1-m3.md`](../superpowers/plans/2026-08-21-smart-routing-m1-m3.md)  
**Ranking-contract sign-off:** [`2026-08-21-m1-m3-ranking-contract-signoff.md`](2026-08-21-m1-m3-ranking-contract-signoff.md)  
**M4 authorization:** [`2026-08-21-m4-smartclient-authorization.md`](2026-08-21-m4-smartclient-authorization.md)

## Context

AIN Layer 21 is a real multi-provider caller (library pin `9468eeb`). The frozen 0.1.0 static chain works, but wastes attempts when the first configured provider is rate-limited, slow, or near quota exhaustion. That is legitimate, evidence-triggered pressure for an experimental routing layer.

The 2026-08-18 draft proposed a three-phase pool → score → execute engine inspired by OmniRoute's *shape*, not a wholesale port. Principal review of that draft plus the session handoff, the accepted generic-hooks design, and the cancelled artifact-store survey found **AIN-specific policy leaking into library scoring** — principally `tier_routing` as a scoring prior — which violates the 0.1.0 boundary.

## Decision summary

**Approve smart routing in principle. Do not approve the 2026-08-18 draft as written.**

Authorize a **narrowed experimental routing engine** above the frozen 0.1.0 primitives. Do not retrofit ranking into `Client.complete()`. Do not absorb AIN policy. Stop for architecture review after M1–M3, before `SmartClient`.

## Controlling principle

Library = **how** the call runs reliably.  
Caller (AIN) = **why**, with what evidence, and what it may affect.

```text
AIN
 │  tier, task_kind, freshness_required, free_only
 │  QuotaReader / CooldownReader (injected)
 ▼
multiprovider-llm experimental layer    ← v0.2, M1–M3 now
 │  ProviderCatalog (static characteristics)
 │  process-local health / latency / lockout
 │  ranking + LKGP
 ▼
Client / adapters / fallback / limiter  ← frozen 0.1.0
 ▼
Providers
```

AIN `tier_routing` stays in AIN. It must not enter library scoring.

## D1–D9

| ID | Question | Outcome |
| :--- | :--- | :--- |
| **D1** | Separate `SmartClient` vs merge into `Client`? | **Accept separate.** Frozen `Client` always chain. Experimental `SmartClient` always smart. |
| **D2** | Catalog ownership / shape | **Accept library builtin** + optional path override. Abstraction is a generic **`ProviderCatalog`**, not AIN/free-tier economics. |
| **D3** | Model lockout persistence | **In-process only** in v0.2. AIN disk cooldown remains authoritative across restarts. |
| **D4** | Health metrics source | **Library process-local rolling window** from `AttemptRecord`. Injectable override optional. |
| **D5** | Catalog size | **Start ~25.** Do not commit to ~40 until soak evidence. |
| **D6** | Default AIN to smart | **Only after soak.** Chain remains AIN default until then. |
| **D7** | Provider circuit breaker | **Defer.** |
| **D8** | Task fitness beyond catalog `tier_affinity` | **Defer.** No prompt classification, no keyword intent, no LLM-as-router. |
| **D9** | May library scoring consume AIN `tier_routing`? | **No.** `tier_fit = catalog.tier_affinity[tier]`. No AIN routing prior in v0.2. |

## What this ADR authorizes now

| Milestone | Scope |
| :--- | :--- |
| **M1** | Generic `ProviderCatalog` + candidate pool + credential / `freshness_ok` / `free_only` filtering |
| **M2** | Process-local model lockout + HTTP/provider-contract error classifier + prefilter |
| **M3** | Quota / health / latency / tier scoring with context-aware weight normalization + boring LKGP |

Then **stop** for architecture review. M4 (`SmartClient` execution API) is not authorized by this ADR.

**2026-08-21 follow-up:** M1–M3 ranking contract signed off; M4 authorized, sliced, implemented, and **implementation-reviewed APPROVED**. Merge/push/PR and M5–M7 remain unauthorized. See [`2026-08-21-m4-implementation-review.md`](2026-08-21-m4-implementation-review.md).

## What remains locked (unchanged from 0.1.0)

- No named Groq / OpenRouter / Ollama presets
- No TPM in public config
- No Redis / durable library storage
- No prompt-text routing / bandit / model learning
- `json_schema` wire-forward still deferred
- `CompletionHooks` stay optional, domain-agnostic, non-control-flow
- Artifact-store extraction stays **cancelled**
- Dual-layer quotas: catalog is static characteristics; runtime quota is injected `QuotaReader`

## Routing selection

Do **not** implement three dispatch mechanisms.

| Mechanism | v0.2 |
| :--- | :--- |
| `Client` | Always chain (frozen) |
| `SmartClient` | Always smart (experimental; M4+) |
| `LibraryConfig.routing_mode` as construction hint | Allowed later if needed to pick which class to build |
| `Client.complete(..., routing_mode=...)` | **Forbidden** — would unfreeze 0.1.0 |

## Consequences

- The 0.1.0 freeze stands. This is an evidence-triggered experimental layer, not a core-contract change.
- Implementers must not copy AIN `tier_routing` into `scoring.py`.
- Catalog `monthly_tokens` is documentation of known/static characteristics, not a runtime quota.
- Scoring weights stay experimental; do not tune them before soak data.
- No v0.2 implementation PR should include `SmartClient` until an M4 slice exists and freeze tests stay green.
- `SmartClient` must use `classify_error`, not frozen `is_retryable`.
- `RankedTarget.score` is comparative; `0.0` is not “unhealthy.”
