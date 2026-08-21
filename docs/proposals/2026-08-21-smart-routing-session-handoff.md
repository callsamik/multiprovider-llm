# Session handoff: Smart routing experimental layer (v0.2, architect-revised)

**Date:** 2026-08-21  
**Status:** Architect-revised; **M1–M3 implemented on this branch**, awaiting ranking-contract architecture review; **M4 gated / STOPPED**; **no v0.2 PR**  
**Use:** Attach this file to a new AI session to resume without prior chat context.

---

## 1. One-paragraph summary

Smart routing is **approved in principle** as an evidence-triggered **experimental layer above frozen 0.1.0 primitives**. It is **not** approved as the 2026-08-18 draft was written. AIN has a real multi-provider path and the static chain has measurable inefficiency, but AIN-specific policy (`tier_routing`) must not enter library scoring. Catalog is a generic `ProviderCatalog`. `Client` stays frozen (always chain). `SmartClient` is separate and **gated until after M1–M3**. Artifact-store stays cancelled. Generic `CompletionHooks` need no redesign. **No PRs exist yet** for v0.2; Layer 21 bridge work is already shipped in AIN (PRs #27, #34, #35) on library pin `9468eeb`.

---

## 2. Repositories & local paths

| Repo | Role | Local path (operator machine) |
| :--- | :--- | :--- |
| **multiprovider-llm** | Library — canonical v0.2 design | `PlaygroundProjects/multiprovider-llm` (also `Projects/multiprovider-llm`) |
| **Autonomous Investment Navigator** | Primary consumer (Layer 21) | `PlaygroundProjects/AutonomousInvestmentNavigator-main` |
| **OmniRoute** | Reference architecture only (not a dependency) | `PlaygroundProjects/OmniRoute` |

**GitHub (operator):**

- Library: `https://github.com/callsamik/multiprovider-llm`
- AIN: `https://github.com/callsamik/AutonomousInvestmentNavigator`

---

## 3. Documentation map (single source of truth)

| Document | Repo | Purpose |
| :--- | :--- | :--- |
| [`2026-08-21-smart-routing-experimental-layer.md`](../decisions/2026-08-21-smart-routing-experimental-layer.md) | **multiprovider-llm** | **Controlling ADR** — narrowed v0.2, D1–D9, M1–M3 gate |
| [`2026-08-18-smart-routing-free-tiers-design.md`](2026-08-18-smart-routing-free-tiers-design.md) | **multiprovider-llm** | **Canonical design** (architect-revised 2026-08-21) |
| [`2026-08-21-smart-routing-session-handoff.md`](2026-08-21-smart-routing-session-handoff.md) | **multiprovider-llm** | **This file** |
| [`2026-08-21-smart-routing-m1-m3.md`](../superpowers/plans/2026-08-21-smart-routing-m1-m3.md) | **multiprovider-llm** | **M1–M3 implementation plan** (no SmartClient) |
| [`2026-08-15-architecture-freeze-0.1.0.md`](../decisions/2026-08-15-architecture-freeze-0.1.0.md) | **multiprovider-llm** | Freeze — **not reopened** |
| [`2026-08-15-generic-policy-hooks-design.md`](2026-08-15-generic-policy-hooks-design.md) | **multiprovider-llm** | Accepted v1.1; confirms domain-agnostic boundary |
| [`2026-08-15-artifact-store-extraction-survey-and-design.md`](2026-08-15-artifact-store-extraction-survey-and-design.md) | **multiprovider-llm** | **Cancelled** — no action |
| AIN `docs/superpowers/specs/2026-08-18-multiprovider-smart-routing-ain-integration.md` | **AIN** | AIN-only glue (must drop `tier_routing`→library scoring) |

**Rule:** Edit library design in multiprovider-llm only. Edit AIN integration in AIN only. Never maintain two full copies.

---

## 4. Current production state (shipped)

### AIN Layer 21 (merged 2026-08-15)

| PR | What |
| :--- | :--- |
| **#27** | Bridge — Gemini/Groq HTTP via multiprovider-llm adapters |
| **#34** | Default-on multiprovider bridge |
| **#35** | Soft de-dupe + hard cutover; Ollama on Client (`complete_via_client`) |

- **Library pin:** `multiprovider-llm@9468eeb` (0.1.0 architecture freeze)
- **Routing today:** static `tier_routing` order per complexity tier via frozen `Client`
- **Key AIN files:** `src/ain/ai_live/provider_bridge.py`, `src/ain/ai_live/providers.py`, `config/ai_providers.json`

### multiprovider-llm v0.1.0a1

- `Client.complete()` with `provider_chain`, `tier`, `freshness_required`, `on_auth_failure="continue"`
- No `SmartClient`, no catalog, no quota-aware ranking — **and `Client.complete` must not grow `routing_mode`**

---

## 5. Approved direction (M1–M3 implemented; M4 gated)

M1–M3 ranking primitives are implemented on this branch. Architect review of the ranking contract is required before M4 (`SmartClient`).

### Controlling principle

Library = how the call runs reliably. AIN = why, with what evidence, and what it may affect.

### Chain vs smart

| Client | Behavior |
| :--- | :--- |
| **`Client` (frozen)** | Static config order per tier; current behavior |
| **`SmartClient` (experimental, M4 gated)** | Pool → pre-filter → 5-factor score → ranked fallback + model lockout + LKGP |

AIN chooses which object to construct. Do not dispatch inside `Client.complete()`.

### What the library may use to score

- Catalog `tier_affinity`
- Runtime health (process-local rolling `AttemptRecord`)
- Injected quota reader
- Latency (same rolling window)
- Cost (omitted when constant, e.g. all-free under `free_only`)
- Execution via frozen adapters

### What must not enter library scoring

- AIN `tier_routing`
- Prompt text / intent classification
- Catalog `monthly_tokens` as if it were remaining quota
- Bandit / exploration

**AIN passes:** `tier`, `task_kind`, `freshness_required`, `free_only`  
**Library must not** parse prompt text, classify intent, or read AIN routing tables.

`freshness_required=True` means: exclude catalog entries with `freshness_ok=false`. It does **not** mean the library decides whether the task needs fresh information.

---

## 6. Explicit non-goals

- OAuth flows for multiprovider-llm / AIN
- Coding-agent providers as primary backends
- Porting full OmniRoute (90+ providers, 14 factors, bandit, gateway UI)
- OmniRoute as a dependency; dumping OmniRoute body-string heuristics
- LLM-as-router, embedding routing, keyword intent
- Bandit exploration
- Distributed rate limiting (Redis) in v0.2
- `json_schema` wire-forward
- Named Groq / OpenRouter / Ollama presets
- Artifact-store extraction
- Caller-supplied routing prior in v0.2
- Implementing `SmartClient` before M1–M3 review

---

## 7. AIN changes (only after M4 is authorized)

**Until then:** no AIN code changes required. Chain/`Client` stays the production path.

When M5 is later authorized: construct `SmartClient`, inject readers, pass `tier` / `task_kind` / `freshness_required` / `free_only`. **Do not** feed `tier_routing` into scoring. `validate_tier_routing()` remains AIN chain policy.

---

## 8. D1–D9 (resolved 2026-08-21)

| ID | Question | Outcome |
| :--- | :--- | :--- |
| D1 | Separate `SmartClient` vs merge into `Client`? | **Separate** — preserves frozen 0.1.0 |
| D2 | Catalog | **Library builtin** + override; generic **`ProviderCatalog`** |
| D3 | Model lockout persistence | **In-process v0.2** |
| D4 | Health metrics source | **Library process-local rolling window**; injectable override optional |
| D5 | Catalog size | **Start ~25**; do not commit to 40 until evidence |
| D6 | Default AIN to smart | **After soak** |
| D7 | Provider circuit breaker | **Defer** |
| D8 | Task fitness beyond `tier_affinity` | **Defer**; no prompt classification |
| D9 | May scoring consume AIN `tier_routing`? | **No** |

---

## 9. Implementation roadmap

| Milestone | Owner | Status |
| :--- | :--- | :--- |
| **M1** | Library | **Implemented (this branch)** — catalog, pool, credential/freshness/free filters; awaiting ranking-contract architecture review |
| **M2** | Library | **Implemented (this branch)** — lockout, error classifier, prefilter; awaiting ranking-contract architecture review |
| **M3** | Library | **Implemented (this branch)** — scoring, LKGP, `QuotaReader`; awaiting ranking-contract architecture review |
| **Review** | Architect | **Required** before M4 |
| **M4** | Library | Gated — `SmartClient` |
| **M5** | AIN | Gated — bridge + readers |
| **M6** | Both | Gated — soak |
| **M7** | Both | Gated — GA |

---

## 10. Eval / soak plan (M6, gated)

**Method:** A/B chain (`Client`) vs smart (`SmartClient`) on live brief worker, same API keys, 1 week.

| Metric | Pass |
| :--- | :--- |
| Live brief success rate | ≥ chain baseline |
| Mean attempts per successful brief | ≤ chain |
| p95 brief latency | ≤ chain + 10% |
| `free_only` violations | 0 |
| Freshness violations (Ollama on live) | 0 |
| Rollback | construct `Client` again |

**Scenarios:**

1. Groq model 429 → smart lockout avoids that `(provider, model)` on the next request
2. Repeat live briefs → LKGP stickiness on `{tier}:{task_kind}`
3. Complex vs simple → AIN `assess_request_complexity()` drives `tier`; library does not read prompt

**CI:** existing `test_client.py` remains green; D9 tests prove AIN routing order does not affect score.

---

## 11. OmniRoute reference pointers (read-only)

| Topic | Path |
| :--- | :--- |
| Auto combo scoring (14 factors) | `OmniRoute/open-sse/services/autoCombo/scoring.ts` |
| Intent classifier (keyword) — **do not port** | `OmniRoute/open-sse/services/intentClassifier.ts` |
| Task fitness table — **deferred** | `OmniRoute/open-sse/services/autoCombo/taskFitness.ts` |
| Error classifier — cherry-pick HTTP signals only | `OmniRoute/open-sse/services/accountFallback.ts` |
| Free tier catalog — inspiration for static entries, not naming | `OmniRoute/open-sse/config/freeModelCatalog.data.ts` |

---

## 12. Uncommitted / next git step

Bring into the library repo (this revision):

- `docs/decisions/2026-08-21-smart-routing-experimental-layer.md`
- `docs/proposals/2026-08-18-smart-routing-free-tiers-design.md` (revised)
- `docs/proposals/2026-08-21-smart-routing-session-handoff.md` (this file)
- Cross-links in freeze ADR, `design.md`, README

**Written spec review = PASS (2026-08-21).** M1–M3 may proceed from the plan below. Implementation of M4 is forbidden until the M1–M3 ranking-contract review.

**M1–M3 implementation plan (authorized):** [`docs/superpowers/plans/2026-08-21-smart-routing-m1-m3.md`](../superpowers/plans/2026-08-21-smart-routing-m1-m3.md)

**M1–M3 code (this branch):** catalog, pool, prefilter, lockout, classifier, scoring, LKGP, and `rank_candidates` are implemented on this branch. Freeze guards live in `tests/test_smart_routing_freeze.py` (skips `tier_routing` only when `path == routing/chain.py` — frozen 0.1.0 Client chain).

AIN integration spec should be updated (in the AIN repo) to remove any `tier_routing` → library scoring language when that repo is available.

---

## 13. Prompt for a new AI session

```text
Context: multiprovider-llm v0.2 smart routing — architect-revised 2026-08-21.

Read first:
1. docs/decisions/2026-08-21-smart-routing-experimental-layer.md (controlling ADR)
2. docs/proposals/2026-08-21-smart-routing-session-handoff.md (this handoff)
3. docs/proposals/2026-08-18-smart-routing-free-tiers-design.md (revised design)
4. docs/decisions/2026-08-15-architecture-freeze-0.1.0.md (not reopened)

Constraints:
- Client always chain; SmartClient always smart; no routing_mode on Client.complete()
- D9: no AIN tier_routing in library scoring; tier_fit = catalog.tier_affinity[tier]
- Generic ProviderCatalog; monthly_tokens is static, not quota
- M1–M3 only until architecture review; do not implement SmartClient yet
- no OAuth, no bandit, no OmniRoute dependency, no prompt-text routing, no Redis, no TPM, no named presets
- artifact-store stays cancelled
- docs split by repo — do not duplicate full specs

Current task: [FILL IN — e.g. "review the revised spec" or "implement M1 catalog"]
```

---

## 14. Approval checklist (principal architect)

- [x] Boundary matrix — library does not absorb AIN policy
- [x] Query-aware boundary — AIN supplies tier; no prompt-text routing in v0.2
- [x] Catalog — generic `ProviderCatalog`; start ~25
- [x] D9 — no AIN `tier_routing` in scoring
- [x] Dual cooldown — AIN disk authoritative; library in-process + injected readers
- [x] D1–D9 resolved
- [x] M1–M3 authorized; M4 gated
- [x] 0.1.0 freeze not reopened
- [x] Written spec reviewed in-repo before M1 coding starts
- [x] M1–M3 code complete; candidate/ranking contract ready for architect review

---

*End of handoff.*
