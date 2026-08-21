# Smart routing M1–M3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a generic, testable candidate/ranking contract (catalog → pool → prefilter → score → LKGP) that a future `SmartClient` can call without redesign — and stop there.

**Status (2026-08-21):** Plan complete. Ranking-contract architecture review **APPROVED**. M4 (`smart_client.py`) remains **out of this plan**. The M4 slice lives in [`2026-08-21-smart-routing-m4-slice.md`](2026-08-21-smart-routing-m4-slice.md). Coding waits on an explicit start.

**Architecture:** New experimental modules sit *beside* frozen `Client` / `routing.py`. They do not change `Client.complete()`, do not add `routing_mode`, and do not read AIN `tier_routing` or prompt text. M4 (`smart_client.py`) is out of this plan.

**Tech Stack:** Python `>=3.11,<4`, stdlib + existing `httpx` (classifier only), pytest; package under `src/multiprovider_llm/`.

**Spec:** [`docs/proposals/2026-08-18-smart-routing-free-tiers-design.md`](../../proposals/2026-08-18-smart-routing-free-tiers-design.md) (architect-revised). **ADR:** [`docs/decisions/2026-08-21-smart-routing-experimental-layer.md`](../../decisions/2026-08-21-smart-routing-experimental-layer.md). **Sign-off:** [`docs/decisions/2026-08-21-m1-m3-ranking-contract-signoff.md`](../../decisions/2026-08-21-m1-m3-ranking-contract-signoff.md). **Freeze:** [`docs/decisions/2026-08-15-architecture-freeze-0.1.0.md`](../../decisions/2026-08-15-architecture-freeze-0.1.0.md).

## Global Constraints

- Python `>=3.11,<4`; dependency `httpx>=0.27,<1`; no vendor SDKs; no OmniRoute import.
- Do **not** create `src/multiprovider_llm/smart_client.py`.
- Do **not** add `routing_mode` to `LibraryConfig`, `Client.complete`, or `AsyncClient.acomplete`.
- Do **not** modify `Client`, `AsyncClient`, or chain `routing.py` except if a freeze-guard test lives in `tests/`.
- Do **not** add AIN types, `tier_routing`, `routing_prior`, prompt/messages parameters, bandit, Redis, TPM, or named Groq/OpenRouter/Ollama *presets*.
- Catalog `monthly_tokens` is static metadata. Scoring and prefilter must not read it as remaining quota.
- `tier_fit` comes only from `catalog.tier_affinity[tier]` (D9).
- `freshness_required=True` means drop `freshness_ok is False`. The library does not decide that a task needs freshness.
- Health / model lockout / LKGP are process-local (`time.monotonic()`). No disk, no Redis.
- New types live in experimental modules — do **not** add them to frozen `src/multiprovider_llm/types.py`.
- Do **not** add experimental ranking symbols to top-level `multiprovider_llm.__all__` (import from submodules).
- Package version stays `0.1.0a1`.
- Readers return `None` for unknown (spec “default 1.0 if unknown”).
- Every task’s requirements implicitly include this section.

## File map

| Path | Responsibility | Milestone |
| :--- | :--- | :--- |
| `src/multiprovider_llm/catalog/__init__.py` | Re-export catalog types + loaders | M1 |
| `src/multiprovider_llm/catalog/provider_catalog.py` | `ProviderCatalogEntry`, `ProviderCatalog`, JSON/mapping load + validate | M1 |
| `src/multiprovider_llm/catalog/data/providers_v1.json` | Builtin static catalog (~25 entries) | M1 |
| `src/multiprovider_llm/catalog/credentials.py` | `CredentialResolver` protocol + `EnvCredentialResolver` | M1 |
| `src/multiprovider_llm/routing/__init__.py` | Re-export pool / rank contract | M1–M3 |
| `src/multiprovider_llm/routing/types.py` | `Candidate`, `ScoringFactors`, `ScoringWeights`, `RankedTarget`, `FilterNote`, `RoutingDiagnostics`, `RankingResult` | M1–M3 |
| `src/multiprovider_llm/routing/pool.py` | `build_candidate_pool()` | M1 |
| `src/multiprovider_llm/resilience/__init__.py` | Re-export lockout + classifier | M2 |
| `src/multiprovider_llm/resilience/model_lockout.py` | `ModelLockoutTracker` | M2 |
| `src/multiprovider_llm/resilience/error_classifier.py` | `FallbackDecision`, `classify_error()` | M2 |
| `src/multiprovider_llm/routing/prefilter.py` | Hard exclusion before scoring | M2 |
| `src/multiprovider_llm/protocols.py` | Add `QuotaReader`, `CooldownReader`, `HealthMetricsReader` | M2–M3 |
| `src/multiprovider_llm/routing/scoring.py` | Factor build, constant-factor drop, `calculate_score` | M3 |
| `src/multiprovider_llm/routing/metrics.py` | `RollingHealthMetrics` | M3 |
| `src/multiprovider_llm/routing/lkgp.py` | Boring LKGP store | M3 |
| `src/multiprovider_llm/routing/rank.py` | **`rank_candidates()` — M4 call surface** | M3 |
| `tests/test_catalog.py` | Catalog load / validate / builtin size | M1 |
| `tests/test_pool.py` | Credential / free / freshness / enabled filters | M1 |
| `tests/test_model_lockout.py` | Process-local `(provider, model)` lockout | M2 |
| `tests/test_error_classifier.py` | Table-driven HTTP + small body set | M2 |
| `tests/test_prefilter.py` | Lockout / cooldown / quota cutoff / missing adapter | M2 |
| `tests/test_scoring.py` | Weights, constants, D9, `monthly_tokens` ignored | M3 |
| `tests/test_metrics.py` | Rolling window health / p95 | M3 |
| `tests/test_lkgp.py` | 10% band promote / forget on failure | M3 |
| `tests/test_rank.py` | End-to-end ranking contract + diagnostics | M3 |
| `tests/test_smart_routing_freeze.py` | Frozen `Client` surface; no `smart_client.py` | M1–M3 |

**Do not create:** `src/multiprovider_llm/smart_client.py`, `resilience/circuit_breaker.py`, catalog files named `free_tiers*` / `api_key_free*`.

## Candidate / ranking contract (what M4 will call)

This is the stopping artifact. After Task 11, M4 must be able to:

```python
from multiprovider_llm.catalog import load_catalog
from multiprovider_llm.catalog.credentials import EnvCredentialResolver
from multiprovider_llm.routing.pool import build_candidate_pool
from multiprovider_llm.routing.rank import rank_candidates
from multiprovider_llm.routing.lkgp import LkgpStore
from multiprovider_llm.routing.metrics import RollingHealthMetrics
from multiprovider_llm.resilience.model_lockout import ModelLockoutTracker

catalog = load_catalog()  # or load_catalog(path=override)
pool = build_candidate_pool(
    catalog,
    credentials=EnvCredentialResolver(environ),
    tier="standard",
    free_only=True,
    freshness_required=True,
    enabled_providers=frozenset({"gemini", "groq", "openrouter"}),
)
result = rank_candidates(
    pool,
    tier="standard",
    task_kind="live_brief",
    lockout=ModelLockoutTracker(),
    lkgp=LkgpStore(),
    quota_reader=...,          # optional
    cooldown_reader=...,       # optional
    health_reader=RollingHealthMetrics(),  # optional
    known_adapters=frozenset({"gemini", "anthropic", "openai_compat"}),
)
# result.ranked_targets: tuple[RankedTarget, ...]
# result.diagnostics: RoutingDiagnostics
```

M4 (not this plan) will iterate `result.ranked_targets`, call adapters, `classify_error`, `lockout.lock`, `lkgp.remember` / `lkgp.forget`, `health_reader.record`. This plan only *produces* the rank list and the primitives M4 will need.

**Forbidden signatures** (asserted in tests): `build_candidate_pool` and `rank_candidates` must not accept `tier_routing`, `routing_prior`, `provider_order`, `preferred_providers`, `prompt`, `messages`, or `routing_mode`.

---

### Task 1: Catalog types and loader

**Files:**
- Create: `src/multiprovider_llm/catalog/__init__.py`
- Create: `src/multiprovider_llm/catalog/provider_catalog.py`
- Create: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `ConfigError` from `multiprovider_llm.errors`
- Produces:
  - `ProviderCatalogEntry` (frozen dataclass; fields listed in Step 3)
  - `ProviderCatalog(catalog_id: str, entries: tuple[ProviderCatalogEntry, ...])`
  - `load_catalog_from_mapping(data: Mapping[str, Any]) -> ProviderCatalog`
  - `load_catalog(*, path: Path | None = None) -> ProviderCatalog` (builtin path used in Task 2; Task 1 may raise `ConfigError` if default file missing — Task 2 adds the file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog.py`:

```python
import pytest

from multiprovider_llm.catalog import ProviderCatalogEntry, load_catalog_from_mapping
from multiprovider_llm.errors import ConfigError


def _entry(**overrides):
    base = {
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "display_name": "Gemini Flash",
        "adapter": "gemini",
        "auth": "api_key",
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "cost_tier": "free",
        "capabilities": {},
        "freshness_ok": True,
        "tier_affinity": {"simple": 0.7, "standard": 1.0, "complex": 0.8},
        "monthly_tokens": 1_000_000,
        "pool_key": None,
        "http_referer": None,
        "enabled_by_default": True,
    }
    base.update(overrides)
    return base


def test_load_catalog_from_mapping_round_trip():
    catalog = load_catalog_from_mapping(
        {"catalog_id": "test:v1", "entries": [_entry()]}
    )
    assert catalog.catalog_id == "test:v1"
    assert len(catalog.entries) == 1
    e = catalog.entries[0]
    assert isinstance(e, ProviderCatalogEntry)
    assert e.provider == "gemini"
    assert e.cost_tier == "free"
    assert e.monthly_tokens == 1_000_000
    assert e.tier_affinity["standard"] == 1.0


def test_unknown_entry_key_raises():
    with pytest.raises(ConfigError, match="unknown"):
        load_catalog_from_mapping(
            {"catalog_id": "t", "entries": [_entry(ain_tier_routing=["groq"])]}
        )


def test_invalid_adapter_raises():
    with pytest.raises(ConfigError, match="adapter"):
        load_catalog_from_mapping(
            {"catalog_id": "t", "entries": [_entry(adapter="groq_preset")]}
        )


def test_auth_none_allows_null_api_key_env():
    catalog = load_catalog_from_mapping(
        {
            "catalog_id": "t",
            "entries": [
                _entry(
                    provider="ollama",
                    model="llama3.2",
                    adapter="openai_compat",
                    auth="none",
                    api_key_env=None,
                    base_url="http://127.0.0.1:11434/v1",
                    freshness_ok=False,
                    monthly_tokens=None,
                )
            ],
        }
    )
    assert catalog.entries[0].auth == "none"
    assert catalog.entries[0].api_key_env is None


def test_affinity_out_of_range_raises():
    with pytest.raises(ConfigError, match="tier_affinity"):
        load_catalog_from_mapping(
            {"catalog_id": "t", "entries": [_entry(tier_affinity={"standard": 1.5})]}
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_catalog.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'multiprovider_llm.catalog'` (or import error for `load_catalog_from_mapping`).

- [ ] **Step 3: Write minimal implementation**

`src/multiprovider_llm/catalog/provider_catalog.py`:

```python
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..errors import ConfigError

_ADAPTERS = frozenset({"gemini", "anthropic", "openai_compat"})
_AUTH = frozenset({"api_key", "none"})
_COST = frozenset({"free", "paid"})
_ENTRY_FIELDS = frozenset(
    {
        "provider",
        "model",
        "display_name",
        "adapter",
        "auth",
        "api_key_env",
        "base_url",
        "cost_tier",
        "capabilities",
        "freshness_ok",
        "tier_affinity",
        "monthly_tokens",
        "pool_key",
        "http_referer",
        "enabled_by_default",
    }
)
_TOP_FIELDS = frozenset({"catalog_id", "entries"})


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
    capabilities: Mapping[str, object]
    freshness_ok: bool
    tier_affinity: Mapping[str, float]
    monthly_tokens: int | None
    pool_key: str | None
    http_referer: str | None
    enabled_by_default: bool


@dataclass(frozen=True)
class ProviderCatalog:
    catalog_id: str
    entries: tuple[ProviderCatalogEntry, ...]


def load_catalog_from_mapping(data: Mapping[str, Any]) -> ProviderCatalog:
    if not isinstance(data, Mapping):
        raise ConfigError("catalog must be a mapping")
    unknown = set(data) - _TOP_FIELDS
    if unknown:
        raise ConfigError(f"unknown catalog keys: {sorted(unknown)!r}")
    catalog_id = data.get("catalog_id")
    if not isinstance(catalog_id, str) or not catalog_id:
        raise ConfigError("catalog_id must be a non-empty string")
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise ConfigError("entries must be a list")
    entries = tuple(_parse_entry(item, index=i) for i, item in enumerate(raw_entries))
    return ProviderCatalog(catalog_id=catalog_id, entries=entries)


def load_catalog(*, path: Path | None = None) -> ProviderCatalog:
    target = path if path is not None else _builtin_path()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"catalog file not found: {target}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"catalog is not valid JSON: {target}") from exc
    if not isinstance(payload, Mapping):
        raise ConfigError("catalog JSON must be an object")
    return load_catalog_from_mapping(payload)


def _builtin_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "providers_v1.json"


def _parse_entry(raw: object, *, index: int) -> ProviderCatalogEntry:
    context = f"entries[{index}]"
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{context} must be a mapping")
    unknown = set(raw) - _ENTRY_FIELDS
    if unknown:
        raise ConfigError(f"unknown keys in {context}: {sorted(unknown)!r}")
    adapter = raw.get("adapter")
    if adapter not in _ADAPTERS:
        raise ConfigError(f"adapter in {context} must be one of {sorted(_ADAPTERS)}")
    auth = raw.get("auth")
    if auth not in _AUTH:
        raise ConfigError(f"auth in {context} must be one of {sorted(_AUTH)}")
    cost_tier = raw.get("cost_tier")
    if cost_tier not in _COST:
        raise ConfigError(f"cost_tier in {context} must be one of {sorted(_COST)}")
    api_key_env = raw.get("api_key_env")
    if auth == "none":
        if api_key_env is not None and not isinstance(api_key_env, str):
            raise ConfigError(f"api_key_env in {context} must be a string or null")
    else:
        if not isinstance(api_key_env, str) or not api_key_env:
            raise ConfigError(f"api_key_env in {context} must be a non-empty string")
    affinity_raw = raw.get("tier_affinity")
    if not isinstance(affinity_raw, Mapping):
        raise ConfigError(f"tier_affinity in {context} must be a mapping")
    affinity: dict[str, float] = {}
    for key, value in affinity_raw.items():
        if not isinstance(key, str):
            raise ConfigError(f"tier_affinity keys in {context} must be strings")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ConfigError(f"tier_affinity values in {context} must be numbers")
        number = float(value)
        if number < 0.0 or number > 1.0:
            raise ConfigError(f"tier_affinity in {context} must be in [0, 1]")
        affinity[key] = number
    monthly = raw.get("monthly_tokens")
    if monthly is not None and (not isinstance(monthly, int) or isinstance(monthly, bool) or monthly < 0):
        raise ConfigError(f"monthly_tokens in {context} must be a non-negative int or null")
    capabilities = raw.get("capabilities")
    if capabilities is None:
        capabilities = {}
    if not isinstance(capabilities, Mapping):
        raise ConfigError(f"capabilities in {context} must be a mapping")
    pool_key = raw.get("pool_key")
    http_referer = raw.get("http_referer")
    if pool_key is not None and not isinstance(pool_key, str):
        raise ConfigError(f"pool_key in {context} must be a string or null")
    if http_referer is not None and not isinstance(http_referer, str):
        raise ConfigError(f"http_referer in {context} must be a string or null")
    return ProviderCatalogEntry(
        provider=_require_str(raw, "provider", context),
        model=_require_str(raw, "model", context),
        display_name=_require_str(raw, "display_name", context),
        adapter=adapter,
        auth=auth,
        api_key_env=api_key_env,
        base_url=_require_str(raw, "base_url", context),
        cost_tier=cost_tier,
        capabilities=dict(capabilities),
        freshness_ok=_require_bool(raw, "freshness_ok", context),
        tier_affinity=affinity,
        monthly_tokens=monthly,
        pool_key=pool_key,
        http_referer=http_referer,
        enabled_by_default=_require_bool(raw, "enabled_by_default", context),
    )


def _require_str(data: Mapping[str, Any], field: str, context: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} in {context} must be a non-empty string")
    return value


def _require_bool(data: Mapping[str, Any], field: str, context: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise ConfigError(f"{field} in {context} must be a boolean")
    return value
```

`src/multiprovider_llm/catalog/__init__.py`:

```python
from .provider_catalog import ProviderCatalog, ProviderCatalogEntry, load_catalog, load_catalog_from_mapping

__all__ = [
    "ProviderCatalog",
    "ProviderCatalogEntry",
    "load_catalog",
    "load_catalog_from_mapping",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_catalog.py -v`

Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/catalog/__init__.py src/multiprovider_llm/catalog/provider_catalog.py tests/test_catalog.py
git commit -m "$(cat <<'EOF'
Add generic ProviderCatalog loader for experimental smart routing.

EOF
)"
```

---

### Task 2: Builtin `providers_v1.json` (~25 entries)

**Files:**
- Create: `src/multiprovider_llm/catalog/data/providers_v1.json`
- Modify: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `load_catalog()` from Task 1
- Produces: builtin catalog id `builtin:providers_v1` with **20–30** entries (target 25). No OAuth, no scrapers, no coding-agent endpoints. Paid OpenAI/Anthropic rows are allowed with `enabled_by_default: false`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_catalog.py`)

```python
from multiprovider_llm.catalog import load_catalog


def test_builtin_catalog_size_and_id():
    catalog = load_catalog()
    assert catalog.catalog_id == "builtin:providers_v1"
    assert 20 <= len(catalog.entries) <= 30


def test_builtin_catalog_has_no_oauth_auth():
    catalog = load_catalog()
    assert {e.auth for e in catalog.entries} <= {"api_key", "none"}


def test_builtin_catalog_adapters_are_generic():
    catalog = load_catalog()
    assert {e.adapter for e in catalog.entries} <= {"gemini", "anthropic", "openai_compat"}


def test_builtin_includes_local_stale_and_paid_disabled_defaults():
    catalog = load_catalog()
    ollama = [e for e in catalog.entries if e.provider == "ollama"]
    assert ollama
    assert all(e.freshness_ok is False and e.auth == "none" for e in ollama)
    paid_default_off = [
        e for e in catalog.entries if e.cost_tier == "paid" and e.enabled_by_default is False
    ]
    assert paid_default_off
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_catalog.py::test_builtin_catalog_size_and_id -v`

Expected: FAIL with `ConfigError: catalog file not found` (or similar).

- [ ] **Step 3: Write the builtin catalog**

Create `src/multiprovider_llm/catalog/data/providers_v1.json` with **exactly 25** entries. Use this file contents (static snapshot — not live economics). Affinity bands: small/fast `{simple: 1.0, standard: 0.6, complex: 0.2}`, mid `{simple: 0.7, standard: 1.0, complex: 0.7}`, large `{simple: 0.4, standard: 0.8, complex: 1.0}`.

```json
{
  "catalog_id": "builtin:providers_v1",
  "entries": [
    {"provider": "gemini", "model": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash", "adapter": "gemini", "auth": "api_key", "api_key_env": "GEMINI_API_KEY", "base_url": "https://generativelanguage.googleapis.com/v1beta", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.7, "standard": 1.0, "complex": 0.8}, "monthly_tokens": 1000000, "pool_key": "gemini", "http_referer": null, "enabled_by_default": true},
    {"provider": "gemini", "model": "gemini-2.0-flash-lite", "display_name": "Gemini 2.0 Flash-Lite", "adapter": "gemini", "auth": "api_key", "api_key_env": "GEMINI_API_KEY", "base_url": "https://generativelanguage.googleapis.com/v1beta", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": 1000000, "pool_key": "gemini", "http_referer": null, "enabled_by_default": true},
    {"provider": "groq", "model": "llama-3.1-8b-instant", "display_name": "Groq Llama 3.1 8B Instant", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "groq", "http_referer": null, "enabled_by_default": true},
    {"provider": "groq", "model": "llama-3.3-70b-versatile", "display_name": "Groq Llama 3.3 70B", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.4, "standard": 0.8, "complex": 1.0}, "monthly_tokens": null, "pool_key": "groq", "http_referer": null, "enabled_by_default": true},
    {"provider": "groq", "model": "openai/gpt-oss-120b", "display_name": "Groq GPT-OSS 120B", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.4, "standard": 0.8, "complex": 1.0}, "monthly_tokens": null, "pool_key": "groq", "http_referer": null, "enabled_by_default": true},
    {"provider": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free", "display_name": "OpenRouter Llama 3.3 70B free", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.4, "standard": 0.8, "complex": 1.0}, "monthly_tokens": null, "pool_key": "openrouter", "http_referer": "https://localhost", "enabled_by_default": true},
    {"provider": "openrouter", "model": "google/gemma-3-27b-it:free", "display_name": "OpenRouter Gemma 3 27B free", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.7, "standard": 1.0, "complex": 0.7}, "monthly_tokens": null, "pool_key": "openrouter", "http_referer": "https://localhost", "enabled_by_default": true},
    {"provider": "openrouter", "model": "mistralai/mistral-7b-instruct:free", "display_name": "OpenRouter Mistral 7B free", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "openrouter", "http_referer": "https://localhost", "enabled_by_default": true},
    {"provider": "openrouter", "model": "qwen/qwen-2.5-7b-instruct:free", "display_name": "OpenRouter Qwen 2.5 7B free", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "openrouter", "http_referer": "https://localhost", "enabled_by_default": true},
    {"provider": "mistral", "model": "mistral-small-latest", "display_name": "Mistral Small", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "MISTRAL_API_KEY", "base_url": "https://api.mistral.ai/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.7, "standard": 1.0, "complex": 0.7}, "monthly_tokens": null, "pool_key": "mistral", "http_referer": null, "enabled_by_default": true},
    {"provider": "mistral", "model": "open-mistral-nemo", "display_name": "Mistral Nemo", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "MISTRAL_API_KEY", "base_url": "https://api.mistral.ai/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.7, "standard": 1.0, "complex": 0.7}, "monthly_tokens": null, "pool_key": "mistral", "http_referer": null, "enabled_by_default": true},
    {"provider": "cerebras", "model": "llama3.1-8b", "display_name": "Cerebras Llama 3.1 8B", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "CEREBRAS_API_KEY", "base_url": "https://api.cerebras.ai/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "cerebras", "http_referer": null, "enabled_by_default": true},
    {"provider": "cerebras", "model": "llama-3.3-70b", "display_name": "Cerebras Llama 3.3 70B", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "CEREBRAS_API_KEY", "base_url": "https://api.cerebras.ai/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.4, "standard": 0.8, "complex": 1.0}, "monthly_tokens": null, "pool_key": "cerebras", "http_referer": null, "enabled_by_default": true},
    {"provider": "together", "model": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "display_name": "Together Llama 3.1 8B Turbo", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "TOGETHER_API_KEY", "base_url": "https://api.together.xyz/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "together", "http_referer": null, "enabled_by_default": true},
    {"provider": "together", "model": "Qwen/Qwen2.5-7B-Instruct-Turbo", "display_name": "Together Qwen 2.5 7B Turbo", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "TOGETHER_API_KEY", "base_url": "https://api.together.xyz/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "together", "http_referer": null, "enabled_by_default": true},
    {"provider": "together", "model": "mistralai/Mistral-7B-Instruct-v0.3", "display_name": "Together Mistral 7B", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "TOGETHER_API_KEY", "base_url": "https://api.together.xyz/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "together", "http_referer": null, "enabled_by_default": true},
    {"provider": "fireworks", "model": "accounts/fireworks/models/llama-v3p1-8b-instruct", "display_name": "Fireworks Llama 3.1 8B", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "FIREWORKS_API_KEY", "base_url": "https://api.fireworks.ai/inference/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "fireworks", "http_referer": null, "enabled_by_default": true},
    {"provider": "sambanova", "model": "Meta-Llama-3.1-8B-Instruct", "display_name": "SambaNova Llama 3.1 8B", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "SAMBANOVA_API_KEY", "base_url": "https://api.sambanova.ai/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "sambanova", "http_referer": null, "enabled_by_default": true},
    {"provider": "openai", "model": "gpt-4o-mini", "display_name": "OpenAI GPT-4o mini", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1", "cost_tier": "paid", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "openai", "http_referer": null, "enabled_by_default": false},
    {"provider": "openai", "model": "gpt-4o", "display_name": "OpenAI GPT-4o", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1", "cost_tier": "paid", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.4, "standard": 0.8, "complex": 1.0}, "monthly_tokens": null, "pool_key": "openai", "http_referer": null, "enabled_by_default": false},
    {"provider": "anthropic", "model": "claude-3-5-haiku-20241022", "display_name": "Claude 3.5 Haiku", "adapter": "anthropic", "auth": "api_key", "api_key_env": "ANTHROPIC_API_KEY", "base_url": "https://api.anthropic.com", "cost_tier": "paid", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "anthropic", "http_referer": null, "enabled_by_default": false},
    {"provider": "anthropic", "model": "claude-3-5-sonnet-20241022", "display_name": "Claude 3.5 Sonnet", "adapter": "anthropic", "auth": "api_key", "api_key_env": "ANTHROPIC_API_KEY", "base_url": "https://api.anthropic.com", "cost_tier": "paid", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.4, "standard": 0.8, "complex": 1.0}, "monthly_tokens": null, "pool_key": "anthropic", "http_referer": null, "enabled_by_default": false},
    {"provider": "deepseek", "model": "deepseek-chat", "display_name": "DeepSeek Chat", "adapter": "openai_compat", "auth": "api_key", "api_key_env": "DEEPSEEK_API_KEY", "base_url": "https://api.deepseek.com/v1", "cost_tier": "paid", "capabilities": {}, "freshness_ok": true, "tier_affinity": {"simple": 0.7, "standard": 1.0, "complex": 0.7}, "monthly_tokens": null, "pool_key": "deepseek", "http_referer": null, "enabled_by_default": false},
    {"provider": "ollama", "model": "llama3.2", "display_name": "Ollama Llama 3.2", "adapter": "openai_compat", "auth": "none", "api_key_env": null, "base_url": "http://127.0.0.1:11434/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": false, "tier_affinity": {"simple": 1.0, "standard": 0.6, "complex": 0.2}, "monthly_tokens": null, "pool_key": "ollama", "http_referer": null, "enabled_by_default": true},
    {"provider": "ollama", "model": "qwen2.5", "display_name": "Ollama Qwen 2.5", "adapter": "openai_compat", "auth": "none", "api_key_env": null, "base_url": "http://127.0.0.1:11434/v1", "cost_tier": "free", "capabilities": {}, "freshness_ok": false, "tier_affinity": {"simple": 0.7, "standard": 1.0, "complex": 0.7}, "monthly_tokens": null, "pool_key": "ollama", "http_referer": null, "enabled_by_default": true}
  ]
}
```

Count the objects: 2 gemini + 3 groq + 4 openrouter + 2 mistral + 2 cerebras + 3 together + 1 fireworks + 1 sambanova + 2 openai + 2 anthropic + 1 deepseek + 2 ollama = **25**.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_catalog.py -v`

Expected: all PASS, including builtin size `25` within `20..30`.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/catalog/data/providers_v1.json tests/test_catalog.py
git commit -m "$(cat <<'EOF'
Ship static providers_v1 catalog (~25 API-key entries).

EOF
)"
```

---

### Task 3: Candidate pool

**Files:**
- Create: `src/multiprovider_llm/routing/types.py`
- Create: `src/multiprovider_llm/catalog/credentials.py`
- Create: `src/multiprovider_llm/routing/pool.py`
- Create: `src/multiprovider_llm/routing/__init__.py`
- Create: `tests/test_pool.py`

**Interfaces:**
- Consumes: `ProviderCatalog`, `ProviderCatalogEntry`
- Produces:
  - `class CredentialResolver(Protocol): def has_key(self, entry: ProviderCatalogEntry) -> bool`
  - `class EnvCredentialResolver: def __init__(self, environ: Mapping[str, str] | None = None)`
  - `Candidate(provider, model, adapter, base_url, cost_tier, freshness_ok, tier_affinity, http_referer)` — **no `monthly_tokens`, no routing order**
  - `build_candidate_pool(catalog, *, credentials, tier, free_only, freshness_required, enabled_providers=None) -> tuple[Candidate, ...]`
  - `default_enabled_providers(catalog) -> frozenset[str]` — providers with `enabled_by_default=True`; pool does **not** auto-apply this

Pool rules (in order):

1. Include iff `credentials.has_key(entry)` (Env resolver: `auth == "none"` or non-empty env value).
2. If `free_only`: drop `cost_tier == "paid"`.
3. If `freshness_required`: drop `freshness_ok is False`.
4. If `enabled_providers` is not `None`: keep only those providers.
5. Dedupe by `(provider, model)`; first occurrence wins.
6. `tier` is accepted for a stable M4-shaped signature but **must not change membership or order** in M1 (affinity is scoring-only). Ignore it in the pool body aside from accepting the kwarg.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pool.py`:

```python
import inspect

from multiprovider_llm.catalog import load_catalog_from_mapping
from multiprovider_llm.catalog.credentials import EnvCredentialResolver
from multiprovider_llm.routing.pool import build_candidate_pool, default_enabled_providers


def _catalog():
    def e(**kw):
        row = {
            "provider": "gemini",
            "model": "flash",
            "display_name": "g",
            "adapter": "gemini",
            "auth": "api_key",
            "api_key_env": "GEMINI_API_KEY",
            "base_url": "https://example.test/gemini",
            "cost_tier": "free",
            "capabilities": {},
            "freshness_ok": True,
            "tier_affinity": {"standard": 1.0},
            "monthly_tokens": 9,
            "pool_key": None,
            "http_referer": None,
            "enabled_by_default": True,
        }
        row.update(kw)
        return row

    return load_catalog_from_mapping(
        {
            "catalog_id": "t",
            "entries": [
                e(),
                e(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY",
                  base_url="https://example.test/groq", enabled_by_default=True),
                e(provider="openai", model="gpt-4o", adapter="openai_compat", api_key_env="OPENAI_API_KEY",
                  base_url="https://example.test/openai", cost_tier="paid", enabled_by_default=False),
                e(provider="ollama", model="llama3.2", adapter="openai_compat", auth="none",
                  api_key_env=None, base_url="http://127.0.0.1:11434/v1", freshness_ok=False),
                e(provider="gemini", model="flash", display_name="dup"),  # duplicate pair
            ],
        }
    )


def test_pool_requires_credentials_except_auth_none():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier="standard", free_only=False, freshness_required=False
    )
    names = {(c.provider, c.model) for c in pool}
    assert ("gemini", "flash") in names
    assert ("ollama", "llama3.2") in names
    assert ("groq", "8b") not in names
    assert ("openai", "gpt-4o") not in names


def test_free_only_drops_paid():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x", "OPENAI_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=True, freshness_required=False
    )
    assert all(c.cost_tier == "free" for c in pool)
    assert ("openai", "gpt-4o") not in {(c.provider, c.model) for c in pool}


def test_freshness_required_drops_freshness_ok_false():
    catalog = _catalog()
    creds = EnvCredentialResolver({})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=False, freshness_required=True
    )
    assert ("ollama", "llama3.2") not in {(c.provider, c.model) for c in pool}


def test_enabled_providers_intersect():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x", "GROQ_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog,
        credentials=creds,
        tier=None,
        free_only=False,
        freshness_required=False,
        enabled_providers=frozenset({"gemini"}),
    )
    assert {(c.provider, c.model) for c in pool} == {("gemini", "flash")}


def test_default_enabled_providers_does_not_auto_apply():
    catalog = _catalog()
    creds = EnvCredentialResolver({"OPENAI_API_KEY": "x"})
    defaults = default_enabled_providers(catalog)
    assert "openai" not in defaults
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=False, freshness_required=False
    )
    assert ("openai", "gpt-4o") in {(c.provider, c.model) for c in pool}


def test_dedupe_first_wins():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=False, freshness_required=False
    )
    gemini = [c for c in pool if c.provider == "gemini" and c.model == "flash"]
    assert len(gemini) == 1
    assert gemini[0].base_url == "https://example.test/gemini"


def test_candidate_has_no_monthly_tokens():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=False, freshness_required=False
    )
    assert not hasattr(pool[0], "monthly_tokens")


def test_pool_signature_has_no_policy_leaks():
    forbidden = {
        "tier_routing",
        "routing_prior",
        "provider_order",
        "preferred_providers",
        "prompt",
        "messages",
        "routing_mode",
    }
    assert forbidden.isdisjoint(inspect.signature(build_candidate_pool).parameters)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pool.py -v`

Expected: FAIL with module import error.

- [ ] **Step 3: Write minimal implementation**

`src/multiprovider_llm/routing/types.py` — for this task, only `Candidate`:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    adapter: Literal["gemini", "anthropic", "openai_compat"]
    base_url: str
    cost_tier: Literal["free", "paid"]
    freshness_ok: bool
    tier_affinity: Mapping[str, float]
    http_referer: str | None
```

`src/multiprovider_llm/catalog/credentials.py`:

```python
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from .provider_catalog import ProviderCatalogEntry


@runtime_checkable
class CredentialResolver(Protocol):
    def has_key(self, entry: ProviderCatalogEntry) -> bool: ...


class EnvCredentialResolver:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = dict(os.environ if environ is None else environ)

    def has_key(self, entry: ProviderCatalogEntry) -> bool:
        if entry.auth == "none":
            return True
        if not entry.api_key_env:
            return False
        value = self._environ.get(entry.api_key_env)
        return bool(value)
```

`src/multiprovider_llm/routing/pool.py`:

```python
from __future__ import annotations

from collections.abc import Sequence

from ..catalog.credentials import CredentialResolver
from ..catalog.provider_catalog import ProviderCatalog
from .types import Candidate


def default_enabled_providers(catalog: ProviderCatalog) -> frozenset[str]:
    return frozenset(e.provider for e in catalog.entries if e.enabled_by_default)


def build_candidate_pool(
    catalog: ProviderCatalog,
    *,
    credentials: CredentialResolver,
    tier: str | None,
    free_only: bool,
    freshness_required: bool,
    enabled_providers: frozenset[str] | None = None,
) -> tuple[Candidate, ...]:
    del tier  # accepted for a stable call shape; membership is not tier-ranked here
    seen: set[tuple[str, str]] = set()
    out: list[Candidate] = []
    for entry in catalog.entries:
        pair = (entry.provider, entry.model)
        if pair in seen:
            continue
        if not credentials.has_key(entry):
            continue
        if free_only and entry.cost_tier == "paid":
            continue
        if freshness_required and not entry.freshness_ok:
            continue
        if enabled_providers is not None and entry.provider not in enabled_providers:
            continue
        seen.add(pair)
        out.append(
            Candidate(
                provider=entry.provider,
                model=entry.model,
                adapter=entry.adapter,
                base_url=entry.base_url,
                cost_tier=entry.cost_tier,
                freshness_ok=entry.freshness_ok,
                tier_affinity=entry.tier_affinity,
                http_referer=entry.http_referer,
            )
        )
    return tuple(out)
```

`src/multiprovider_llm/routing/__init__.py`:

```python
from .pool import build_candidate_pool, default_enabled_providers
from .types import Candidate

__all__ = ["Candidate", "build_candidate_pool", "default_enabled_providers"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pool.py tests/test_catalog.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/catalog/credentials.py src/multiprovider_llm/routing tests/test_pool.py
git commit -m "$(cat <<'EOF'
Add credentialed candidate pool with generic free/freshness filters.

EOF
)"
```

---

### Task 4: Model lockout

**Files:**
- Create: `src/multiprovider_llm/resilience/__init__.py`
- Create: `src/multiprovider_llm/resilience/model_lockout.py`
- Create: `tests/test_model_lockout.py`

**Interfaces:**
- Consumes: nothing from ranking
- Produces:
  - `ModelLockoutTracker.lock(provider, model, cooldown_s: float | None, *, now=None) -> None` — `cooldown_s is None` means until process exit
  - `is_locked(provider, model, *, now=None) -> bool`
  - `remaining_seconds(provider, model, *, now=None) -> float` — `0.0` if unlocked; `math.inf` if terminal
  - Clock: `time.monotonic()` unless `now=` injected (tests)

- [ ] **Step 1: Write the failing tests**

```python
from multiprovider_llm.resilience.model_lockout import ModelLockoutTracker


def test_lock_expires():
    tracker = ModelLockoutTracker()
    tracker.lock("groq", "llama-3.1-8b-instant", 10.0, now=100.0)
    assert tracker.is_locked("groq", "llama-3.1-8b-instant", now=105.0)
    assert tracker.is_locked("groq", "llama-3.1-8b-instant", now=110.0) is False
    assert tracker.is_locked("groq", "other-model", now=105.0) is False
    assert tracker.is_locked("gemini", "llama-3.1-8b-instant", now=105.0) is False


def test_terminal_lock_never_expires():
    tracker = ModelLockoutTracker()
    tracker.lock("groq", "missing", None, now=1.0)
    assert tracker.is_locked("groq", "missing", now=10**9)
    assert tracker.remaining_seconds("groq", "missing", now=2.0) == float("inf")


def test_remaining_seconds():
    tracker = ModelLockoutTracker()
    tracker.lock("groq", "m", 8.0, now=10.0)
    assert tracker.remaining_seconds("groq", "m", now=12.0) == 6.0
    assert tracker.remaining_seconds("groq", "m", now=20.0) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_model_lockout.py -v`

Expected: FAIL import error.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import math
import threading
import time


class ModelLockoutTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until: dict[tuple[str, str], float] = {}

    def lock(
        self,
        provider: str,
        model: str,
        cooldown_s: float | None,
        *,
        now: float | None = None,
    ) -> None:
        clock = time.monotonic() if now is None else now
        until = math.inf if cooldown_s is None else clock + cooldown_s
        with self._lock:
            self._until[(provider, model)] = until

    def is_locked(self, provider: str, model: str, *, now: float | None = None) -> bool:
        return self.remaining_seconds(provider, model, now=now) > 0.0

    def remaining_seconds(
        self, provider: str, model: str, *, now: float | None = None
    ) -> float:
        clock = time.monotonic() if now is None else now
        with self._lock:
            until = self._until.get((provider, model))
            if until is None:
                return 0.0
            if until == math.inf:
                return math.inf
            left = until - clock
            if left <= 0.0:
                self._until.pop((provider, model), None)
                return 0.0
            return left
```

`src/multiprovider_llm/resilience/__init__.py`:

```python
from .model_lockout import ModelLockoutTracker

__all__ = ["ModelLockoutTracker"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_model_lockout.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/resilience tests/test_model_lockout.py
git commit -m "$(cat <<'EOF'
Add process-local (provider, model) lockout tracker.

EOF
)"
```

---

### Task 5: Error classifier

**Files:**
- Create: `src/multiprovider_llm/resilience/error_classifier.py`
- Modify: `src/multiprovider_llm/resilience/__init__.py`
- Create: `tests/test_error_classifier.py`

**Interfaces:**
- Consumes: `ProviderError`, `RateLimited`, `ValidationError`; `httpx.TimeoutException`, `httpx.ConnectError`
- Produces:
  - `FallbackDecision(should_fallback: bool, lock_model: bool, cooldown_s: float | None, reason: str)`
  - `classify_error(exc, *, on_auth_failure: Literal["stop", "continue"] = "stop") -> FallbackDecision`
  - 429 / `RateLimited`: fallback + lock_model; `cooldown_s` from integer `Retry-After` header or `60.0`
  - 502/503/504/529: fallback, no lock, `cooldown_s=5.0`
  - 500: fallback, no lock, `cooldown_s=1.0`
  - 401/403: lock_model False; fallback only if `on_auth_failure == "continue"`
  - timeout/connect: fallback, no lock, `cooldown_s=1.0`
  - body contains `insufficient_quota` or `credits_exhausted`: fallback + lock, `cooldown_s=60.0`
  - body contains `model_not_found` or `model_not_supported`: fallback + lock, `cooldown_s=None` (terminal)
  - `ValidationError`: fallback, no lock, `cooldown_s=None`
  - HTTP 400: **no** fallback
  - unknown: **no** fallback (fail closed)
  - Body checks are exact substring matches on `ProviderError.body` for those four tokens only. Do not add more heuristics.

- [ ] **Step 1: Write the failing table-driven test**

```python
import httpx
import pytest

from multiprovider_llm.errors import ProviderError, RateLimited, ValidationError
from multiprovider_llm.resilience.error_classifier import classify_error


@pytest.mark.parametrize(
    "exc, on_auth, should_fallback, lock_model, cooldown_s, reason",
    [
        (RateLimited("hot", status_code=429, headers={"Retry-After": "12"}), "stop", True, True, 12.0, "http_429"),
        (ProviderError("x", status_code=429), "stop", True, True, 60.0, "http_429"),
        (ProviderError("x", status_code=503), "stop", True, False, 5.0, "http_unavailable"),
        (ProviderError("x", status_code=502), "stop", True, False, 5.0, "http_unavailable"),
        (ProviderError("x", status_code=504), "stop", True, False, 5.0, "http_unavailable"),
        (ProviderError("x", status_code=529), "stop", True, False, 5.0, "http_unavailable"),
        (ProviderError("x", status_code=500), "stop", True, False, 1.0, "http_500"),
        (ProviderError("x", status_code=401), "stop", False, False, None, "http_auth"),
        (ProviderError("x", status_code=403), "continue", True, False, None, "http_auth"),
        (httpx.TimeoutException("t"), "stop", True, False, 1.0, "timeout"),
        (httpx.ConnectError("c"), "stop", True, False, 1.0, "connect"),
        (ProviderError("insufficient_quota", status_code=400, body="insufficient_quota"), "stop", True, True, 60.0, "quota_exhausted"),
        (ProviderError("credits_exhausted", body="credits_exhausted"), "stop", True, True, 60.0, "quota_exhausted"),
        (ProviderError("missing", status_code=404, body="model_not_found"), "stop", True, True, None, "model_unavailable"),
        (ProviderError("nope", status_code=400, body="model_not_supported"), "stop", True, True, None, "model_unavailable"),
        (ValidationError("json"), "stop", True, False, None, "json_validation"),
        (ProviderError("bad prompt", status_code=400, body="invalid request"), "stop", False, False, None, "http_400"),
        (RuntimeError("boom"), "stop", False, False, None, "unknown"),
    ],
)
def test_classify_error_table(exc, on_auth, should_fallback, lock_model, cooldown_s, reason):
    decision = classify_error(exc, on_auth_failure=on_auth)
    assert decision.should_fallback is should_fallback
    assert decision.lock_model is lock_model
    assert decision.cooldown_s == cooldown_s
    assert decision.reason == reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_error_classifier.py -v`

Expected: FAIL import error.

- [ ] **Step 3: Write minimal implementation**

`src/multiprovider_llm/resilience/error_classifier.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from ..errors import ProviderError, RateLimited, ValidationError

_UNAVAILABLE = frozenset({502, 503, 504, 529})
_AUTH = frozenset({401, 403})


@dataclass(frozen=True)
class FallbackDecision:
    should_fallback: bool
    lock_model: bool
    cooldown_s: float | None
    reason: str


def classify_error(
    exc: BaseException,
    *,
    on_auth_failure: Literal["stop", "continue"] = "stop",
) -> FallbackDecision:
    if isinstance(exc, ValidationError):
        return FallbackDecision(True, False, None, "json_validation")
    if isinstance(exc, httpx.TimeoutException):
        return FallbackDecision(True, False, 1.0, "timeout")
    if isinstance(exc, httpx.ConnectError):
        return FallbackDecision(True, False, 1.0, "connect")
    if isinstance(exc, ProviderError):
        body = (exc.body or "").lower()
        if "insufficient_quota" in body or "credits_exhausted" in body:
            return FallbackDecision(True, True, 60.0, "quota_exhausted")
        if "model_not_found" in body or "model_not_supported" in body:
            return FallbackDecision(True, True, None, "model_unavailable")
        status = exc.status_code
        if status == 429 or isinstance(exc, RateLimited):
            return FallbackDecision(True, True, _retry_after_seconds(exc), "http_429")
        if status in _UNAVAILABLE:
            return FallbackDecision(True, False, 5.0, "http_unavailable")
        if status == 500:
            return FallbackDecision(True, False, 1.0, "http_500")
        if status in _AUTH:
            return FallbackDecision(on_auth_failure == "continue", False, None, "http_auth")
        if status == 400:
            return FallbackDecision(False, False, None, "http_400")
    return FallbackDecision(False, False, None, "unknown")


def _retry_after_seconds(exc: ProviderError) -> float:
    raw = None
    for key, value in exc.headers.items():
        if key.lower() == "retry-after":
            raw = value
            break
    if isinstance(raw, str) and raw.isdigit():
        return float(int(raw))
    if isinstance(raw, int) and not isinstance(raw, bool):
        return float(raw)
    return 60.0
```

Replace `src/multiprovider_llm/resilience/__init__.py` with:

```python
from .error_classifier import FallbackDecision, classify_error
from .model_lockout import ModelLockoutTracker

__all__ = ["FallbackDecision", "ModelLockoutTracker", "classify_error"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_error_classifier.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/resilience/error_classifier.py src/multiprovider_llm/resilience/__init__.py tests/test_error_classifier.py
git commit -m "$(cat <<'EOF'
Add HTTP/provider-contract fallback error classifier.

EOF
)"
```

---

### Task 6: Protocols + prefilter

**Files:**
- Modify: `src/multiprovider_llm/protocols.py`
- Create: `src/multiprovider_llm/routing/prefilter.py`
- Modify: `src/multiprovider_llm/routing/types.py` (add `FilterNote`, `PrefilterResult`)
- Create: `tests/test_prefilter.py`

**Interfaces:**
- Consumes: `Candidate`, `ModelLockoutTracker`
- Produces:

```python
class QuotaReader(Protocol):
    def quota_remaining_pct(self, provider: str, model: str) -> float | None: ...

class CooldownReader(Protocol):
    def is_cooling(self, provider: str) -> bool: ...
    def remaining_seconds(self, provider: str) -> float: ...

class HealthMetricsReader(Protocol):
    def error_rate(self, provider: str, model: str) -> float | None: ...
    def p95_latency_ms(self, provider: str, model: str) -> float | None: ...

@dataclass(frozen=True)
class FilterNote:
    provider: str
    model: str
    reason: str  # lockout | cooldown | quota_cutoff | missing_adapter

@dataclass(frozen=True)
class PrefilterResult:
    eligible: tuple[Candidate, ...]
    notes: tuple[FilterNote, ...]

def prefilter_candidates(
    candidates: Sequence[Candidate],
    *,
    lockout: ModelLockoutTracker,
    quota_reader: QuotaReader | None = None,
    cooldown_reader: CooldownReader | None = None,
    known_adapters: frozenset[str] | None = None,
    min_quota_pct: float = 0.05,
    now: float | None = None,
) -> PrefilterResult:
```

Hard-skip reasons, first match wins per candidate: lockout → cooldown (provider) → quota remaining not `None` and `< min_quota_pct` → `known_adapters is not None` and `candidate.adapter not in known_adapters`.

- [ ] **Step 1: Write the failing tests**

```python
from multiprovider_llm.resilience.model_lockout import ModelLockoutTracker
from multiprovider_llm.routing.prefilter import prefilter_candidates
from multiprovider_llm.routing.types import Candidate


def _c(provider="groq", model="m", adapter="openai_compat"):
    return Candidate(
        provider=provider,
        model=model,
        adapter=adapter,
        base_url="https://example.test",
        cost_tier="free",
        freshness_ok=True,
        tier_affinity={"standard": 1.0},
        http_referer=None,
    )


class Quota:
    def __init__(self, table):
        self.table = table

    def quota_remaining_pct(self, provider, model):
        return self.table.get((provider, model))


class Cool:
    def __init__(self, cooling):
        self.cooling = cooling

    def is_cooling(self, provider):
        return provider in self.cooling

    def remaining_seconds(self, provider):
        return 9.0 if provider in self.cooling else 0.0


def test_lockout_excludes():
    lockout = ModelLockoutTracker()
    lockout.lock("groq", "m", 30.0, now=1.0)
    result = prefilter_candidates((_c(), _c(provider="gemini", model="flash", adapter="gemini")), lockout=lockout, now=2.0)
    assert [c.provider for c in result.eligible] == ["gemini"]
    assert result.notes[0].reason == "lockout"


def test_cooldown_reader_excludes_provider():
    result = prefilter_candidates((_c(),), lockout=ModelLockoutTracker(), cooldown_reader=Cool({"groq"}))
    assert result.eligible == ()
    assert result.notes[0].reason == "cooldown"


def test_quota_cutoff_skips_known_low_keeps_unknown():
    groq = _c()
    gem = _c(provider="gemini", model="flash", adapter="gemini")
    result = prefilter_candidates(
        (groq, gem),
        lockout=ModelLockoutTracker(),
        quota_reader=Quota({("groq", "m"): 0.01, ("gemini", "flash"): None}),
        min_quota_pct=0.05,
    )
    assert [c.provider for c in result.eligible] == ["gemini"]
    assert result.notes[0].reason == "quota_cutoff"


def test_missing_adapter():
    result = prefilter_candidates(
        (_c(adapter="openai_compat"),),
        lockout=ModelLockoutTracker(),
        known_adapters=frozenset({"gemini"}),
    )
    assert result.eligible == ()
    assert result.notes[0].reason == "missing_adapter"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_prefilter.py -v`

Expected: FAIL import error.

- [ ] **Step 3: Write protocols + prefilter**

Append to `src/multiprovider_llm/protocols.py` (after `ProviderAdapter`):

```python
@runtime_checkable
class QuotaReader(Protocol):
    def quota_remaining_pct(self, provider: str, model: str) -> float | None: ...


@runtime_checkable
class CooldownReader(Protocol):
    def is_cooling(self, provider: str) -> bool: ...

    def remaining_seconds(self, provider: str) -> float: ...


@runtime_checkable
class HealthMetricsReader(Protocol):
    def error_rate(self, provider: str, model: str) -> float | None: ...

    def p95_latency_ms(self, provider: str, model: str) -> float | None: ...
```

Append to `src/multiprovider_llm/routing/types.py`:

```python
@dataclass(frozen=True)
class FilterNote:
    provider: str
    model: str
    reason: str


@dataclass(frozen=True)
class PrefilterResult:
    eligible: tuple[Candidate, ...]
    notes: tuple[FilterNote, ...]
```

`src/multiprovider_llm/routing/prefilter.py`:

```python
from __future__ import annotations

from collections.abc import Sequence

from ..protocols import CooldownReader, QuotaReader
from ..resilience.model_lockout import ModelLockoutTracker
from .types import Candidate, FilterNote, PrefilterResult


def prefilter_candidates(
    candidates: Sequence[Candidate],
    *,
    lockout: ModelLockoutTracker,
    quota_reader: QuotaReader | None = None,
    cooldown_reader: CooldownReader | None = None,
    known_adapters: frozenset[str] | None = None,
    min_quota_pct: float = 0.05,
    now: float | None = None,
) -> PrefilterResult:
    eligible: list[Candidate] = []
    notes: list[FilterNote] = []
    for candidate in candidates:
        reason: str | None = None
        if lockout.is_locked(candidate.provider, candidate.model, now=now):
            reason = "lockout"
        elif cooldown_reader is not None and cooldown_reader.is_cooling(candidate.provider):
            reason = "cooldown"
        elif quota_reader is not None:
            remaining = quota_reader.quota_remaining_pct(candidate.provider, candidate.model)
            if remaining is not None and remaining < min_quota_pct:
                reason = "quota_cutoff"
        if reason is None and known_adapters is not None and candidate.adapter not in known_adapters:
            reason = "missing_adapter"
        if reason is not None:
            notes.append(FilterNote(candidate.provider, candidate.model, reason))
            continue
        eligible.append(candidate)
    return PrefilterResult(eligible=tuple(eligible), notes=tuple(notes))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_prefilter.py tests/test_pool.py tests/test_model_lockout.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/protocols.py src/multiprovider_llm/routing/prefilter.py src/multiprovider_llm/routing/types.py tests/test_prefilter.py
git commit -m "$(cat <<'EOF'
Add injectable quota/cooldown protocols and ranking prefilter.

EOF
)"
```

---

### Task 7: Scoring + D9

**Files:**
- Modify: `src/multiprovider_llm/routing/types.py` (add `ScoringFactors`, `ScoringWeights`, `DEFAULT_WEIGHTS`)
- Create: `src/multiprovider_llm/routing/scoring.py`
- Create: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `Candidate`, `QuotaReader`, `HealthMetricsReader`
- Produces:

```python
FACTOR_NAMES = ("quota", "health", "latency_inv", "tier_fit", "cost_inv")

@dataclass(frozen=True)
class ScoringWeights:
    quota: float = 0.30
    health: float = 0.25
    latency_inv: float = 0.20
    tier_fit: float = 0.15
    cost_inv: float = 0.10

@dataclass(frozen=True)
class ScoringFactors:
    quota: float
    health: float
    latency_inv: float
    tier_fit: float
    cost_inv: float

def clamp01(value: float) -> float: ...
def cost_inv_for(candidate: Candidate) -> float:  # 1.0 if free else 0.0
def tier_fit_for(candidate: Candidate, tier: str | None) -> float:  # 1.0 if tier is None; else affinity.get(tier, 0.0)
def quota_factor(reader: QuotaReader | None, candidate: Candidate) -> float:  # None → 1.0
def health_factors(reader: HealthMetricsReader | None, candidate: Candidate) -> tuple[float, float]:
    # (health, latency_inv); None/unknown → (1.0, 1.0)
    # latency_inv = 1 / (1 + p95_ms / 1000)

def factors_for(candidate, *, tier, quota_reader, health_reader) -> ScoringFactors: ...
def constant_factors_across(rows: Sequence[ScoringFactors]) -> frozenset[str]: ...
def calculate_score(factors, weights, *, constant_factors: frozenset[str] = frozenset()) -> float: ...
```

Renormalize remaining weights to sum 1.0. If every factor is constant, `calculate_score` returns `0.0` (ties broken later by provider name).

**D9 / quota honesty:** `factors_for` / `calculate_score` take no `tier_routing`, no caller order, no `monthly_tokens`.

- [ ] **Step 1: Write the failing tests**

```python
import inspect

from multiprovider_llm.routing.scoring import (
    calculate_score,
    constant_factors_across,
    cost_inv_for,
    factors_for,
    tier_fit_for,
)
from multiprovider_llm.routing.types import Candidate, ScoringFactors, ScoringWeights


def _cand(provider="a", model="m", cost_tier="free", affinity=None):
    return Candidate(
        provider=provider,
        model=model,
        adapter="openai_compat",
        base_url="https://example.test",
        cost_tier=cost_tier,
        freshness_ok=True,
        tier_affinity=affinity or {"standard": 0.5, "complex": 1.0},
        http_referer=None,
    )


def test_tier_fit_catalog_only():
    c = _cand(affinity={"standard": 0.2, "complex": 0.9})
    assert tier_fit_for(c, "complex") == 0.9
    assert tier_fit_for(c, "standard") == 0.2
    assert tier_fit_for(c, "simple") == 0.0
    assert tier_fit_for(c, None) == 1.0


def test_cost_inv_free_vs_paid():
    assert cost_inv_for(_cand(cost_tier="free")) == 1.0
    assert cost_inv_for(_cand(cost_tier="paid")) == 0.0


def test_constant_cost_inv_dropped_under_all_free():
    rows = (
        ScoringFactors(quota=0.2, health=1.0, latency_inv=1.0, tier_fit=0.5, cost_inv=1.0),
        ScoringFactors(quota=0.8, health=1.0, latency_inv=1.0, tier_fit=0.5, cost_inv=1.0),
    )
    constant = constant_factors_across(rows)
    assert "cost_inv" in constant
    assert "quota" not in constant
    weights = ScoringWeights()
    low = calculate_score(rows[0], weights, constant_factors=constant)
    high = calculate_score(rows[1], weights, constant_factors=constant)
    assert high > low
    # renormalize: quota 0.30 / (1.0-0.10-0.25-0.20-0.15 wait remaining = quota+tier_fit = 0.45)
    # health and latency also constant → dropped too
    assert "health" in constant and "latency_inv" in constant and "tier_fit" in constant
    assert abs(high - (0.8)) < 1e-9
    assert abs(low - (0.2)) < 1e-9


def test_factors_for_unknown_quota_is_one():
    factors = factors_for(_cand(), tier="standard", quota_reader=None, health_reader=None)
    assert factors.quota == 1.0
    assert factors.health == 1.0
    assert factors.latency_inv == 1.0


def test_d9_signatures_forbid_ain_routing():
    forbidden = {
        "tier_routing",
        "routing_prior",
        "provider_order",
        "preferred_providers",
        "prompt",
        "messages",
        "monthly_tokens",
    }
    assert forbidden.isdisjoint(inspect.signature(factors_for).parameters)
    assert forbidden.isdisjoint(inspect.signature(calculate_score).parameters)
    assert forbidden.isdisjoint(inspect.signature(tier_fit_for).parameters)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scoring.py -v`

Expected: FAIL import error.

- [ ] **Step 3: Write scoring.py**

Append to `src/multiprovider_llm/routing/types.py`:

```python
FACTOR_NAMES = ("quota", "health", "latency_inv", "tier_fit", "cost_inv")


@dataclass(frozen=True)
class ScoringWeights:
    quota: float = 0.30
    health: float = 0.25
    latency_inv: float = 0.20
    tier_fit: float = 0.15
    cost_inv: float = 0.10

    def as_dict(self) -> dict[str, float]:
        return {
            "quota": self.quota,
            "health": self.health,
            "latency_inv": self.latency_inv,
            "tier_fit": self.tier_fit,
            "cost_inv": self.cost_inv,
        }


@dataclass(frozen=True)
class ScoringFactors:
    quota: float
    health: float
    latency_inv: float
    tier_fit: float
    cost_inv: float
```

`src/multiprovider_llm/routing/scoring.py`:

```python
from __future__ import annotations

from collections.abc import Sequence

from ..protocols import HealthMetricsReader, QuotaReader
from .types import FACTOR_NAMES, Candidate, ScoringFactors, ScoringWeights

DEFAULT_WEIGHTS = ScoringWeights()


def clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def cost_inv_for(candidate: Candidate) -> float:
    return 1.0 if candidate.cost_tier == "free" else 0.0


def tier_fit_for(candidate: Candidate, tier: str | None) -> float:
    if tier is None:
        return 1.0
    return float(candidate.tier_affinity.get(tier, 0.0))


def quota_factor(reader: QuotaReader | None, candidate: Candidate) -> float:
    if reader is None:
        return 1.0
    remaining = reader.quota_remaining_pct(candidate.provider, candidate.model)
    if remaining is None:
        return 1.0
    return clamp01(remaining)


def health_factors(
    reader: HealthMetricsReader | None, candidate: Candidate
) -> tuple[float, float]:
    if reader is None:
        return (1.0, 1.0)
    error_rate = reader.error_rate(candidate.provider, candidate.model)
    health = 1.0 if error_rate is None else clamp01(1.0 - error_rate)
    p95 = reader.p95_latency_ms(candidate.provider, candidate.model)
    latency_inv = 1.0 if p95 is None else 1.0 / (1.0 + p95 / 1000.0)
    return (health, latency_inv)


def factors_for(
    candidate: Candidate,
    *,
    tier: str | None,
    quota_reader: QuotaReader | None,
    health_reader: HealthMetricsReader | None,
) -> ScoringFactors:
    health, latency_inv = health_factors(health_reader, candidate)
    return ScoringFactors(
        quota=quota_factor(quota_reader, candidate),
        health=health,
        latency_inv=latency_inv,
        tier_fit=tier_fit_for(candidate, tier),
        cost_inv=cost_inv_for(candidate),
    )


def constant_factors_across(rows: Sequence[ScoringFactors]) -> frozenset[str]:
    if not rows:
        return frozenset()
    constant: set[str] = set()
    for name in FACTOR_NAMES:
        values = {getattr(row, name) for row in rows}
        if len(values) == 1:
            constant.add(name)
    return frozenset(constant)


def calculate_score(
    factors: ScoringFactors,
    weights: ScoringWeights,
    *,
    constant_factors: frozenset[str] = frozenset(),
) -> float:
    active = {k: w for k, w in weights.as_dict().items() if k not in constant_factors}
    total = sum(active.values())
    if total == 0.0:
        return 0.0
    return clamp01(sum((w / total) * float(getattr(factors, k)) for k, w in active.items()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scoring.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/routing/scoring.py src/multiprovider_llm/routing/types.py tests/test_scoring.py
git commit -m "$(cat <<'EOF'
Add context-aware scoring with catalog tier_fit only.

EOF
)"
```

---

### Task 8: Rolling health metrics

**Files:**
- Create: `src/multiprovider_llm/routing/metrics.py`
- Create: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `AttemptRecord` from frozen `types.py`
- Produces: `RollingHealthMetrics(window_size: int = 50)` implementing `HealthMetricsReader` plus `record(attempt: AttemptRecord) -> None`. Key is `(provider, model or "")`. Empty window → `error_rate` and `p95_latency_ms` return `None`. `error_rate = failures / n`. p95: sort latencies, index `min(n-1, max(0, ceil(0.95 * n) - 1))`.

- [ ] **Step 1: Write the failing tests**

```python
from multiprovider_llm.routing.metrics import RollingHealthMetrics
from multiprovider_llm.types import AttemptRecord


def _rec(provider="groq", model="m", ok=True, latency_ms=10.0):
    return AttemptRecord(
        provider=provider,
        model=model,
        ok=ok,
        error_type=None if ok else "RateLimited",
        status_code=200 if ok else 429,
        latency_ms=latency_ms,
        message=None,
    )


def test_empty_window_unknown():
    metrics = RollingHealthMetrics()
    assert metrics.error_rate("groq", "m") is None
    assert metrics.p95_latency_ms("groq", "m") is None


def test_error_rate_and_p95():
    metrics = RollingHealthMetrics(window_size=10)
    for i in range(4):
        metrics.record(_rec(ok=True, latency_ms=10.0 + i))
    metrics.record(_rec(ok=False, latency_ms=50.0))
    assert metrics.error_rate("groq", "m") == 0.2
    assert metrics.p95_latency_ms("groq", "m") == 50.0


def test_window_evicts():
    metrics = RollingHealthMetrics(window_size=2)
    metrics.record(_rec(ok=False, latency_ms=1))
    metrics.record(_rec(ok=False, latency_ms=1))
    metrics.record(_rec(ok=True, latency_ms=1))
    metrics.record(_rec(ok=True, latency_ms=1))
    assert metrics.error_rate("groq", "m") == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics.py -v`

Expected: FAIL import error.

- [ ] **Step 3: Write RollingHealthMetrics**

`src/multiprovider_llm/routing/metrics.py`:

```python
from __future__ import annotations

import math
import threading
from collections import deque

from ..types import AttemptRecord


class RollingHealthMetrics:
    def __init__(self, window_size: int = 50) -> None:
        self._window_size = window_size
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], deque[AttemptRecord]] = {}

    def record(self, attempt: AttemptRecord) -> None:
        key = (attempt.provider, attempt.model or "")
        with self._lock:
            bucket = self._windows.get(key)
            if bucket is None:
                bucket = deque(maxlen=self._window_size)
                self._windows[key] = bucket
            bucket.append(attempt)

    def error_rate(self, provider: str, model: str) -> float | None:
        with self._lock:
            bucket = self._windows.get((provider, model))
            if not bucket:
                return None
            failures = sum(1 for item in bucket if not item.ok)
            return failures / len(bucket)

    def p95_latency_ms(self, provider: str, model: str) -> float | None:
        with self._lock:
            bucket = self._windows.get((provider, model))
            if not bucket:
                return None
            values = sorted(item.latency_ms for item in bucket)
        index = min(len(values) - 1, max(0, math.ceil(0.95 * len(values)) - 1))
        return values[index]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py tests/test_scoring.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/routing/metrics.py tests/test_metrics.py
git commit -m "$(cat <<'EOF'
Add process-local rolling health and latency metrics.

EOF
)"
```

---

### Task 9: LKGP

**Files:**
- Create: `src/multiprovider_llm/routing/lkgp.py`
- Modify: `src/multiprovider_llm/routing/types.py` (add `RankedTarget` if not already present)
- Create: `tests/test_lkgp.py`

**Interfaces:**

```python
class LkgpStore:
    def __init__(self, *, band: float = 0.10, ttl_s: float | None = 1800.0) -> None: ...
    def make_key(self, tier: str | None, task_kind: str | None) -> str:
        # f"{tier or '-'}:{task_kind or '-'}"
    def remember(self, key: str, provider: str, model: str, *, now: float | None = None) -> None: ...
    def forget(self, key: str) -> None: ...
    def get(self, key: str, *, now: float | None = None) -> tuple[str, str] | None: ...
    def promote(
        self, ranked: Sequence[RankedTarget], key: str, *, now: float | None = None
    ) -> tuple[tuple[RankedTarget, ...], bool]:
        # If remembered (provider, model) is in ranked and score >= best_score * (1 - band),
        # move that target to rank 1 (re-number ranks). Return (new_tuple, promoted: bool).
        # No-op if missing, expired, or outside band.
```

`RankedTarget(provider, model, score, factors, rank)` with `rank` 1-based.

TTL uses `time.monotonic()`. `ttl_s is None` means no expiry. On `get` after TTL, forget and return `None`.

No randomness.

- [ ] **Step 1: Write the failing tests**

```python
from multiprovider_llm.routing.lkgp import LkgpStore
from multiprovider_llm.routing.types import RankedTarget, ScoringFactors


def _t(provider, score, rank):
    return RankedTarget(
        provider=provider,
        model="m",
        score=score,
        factors=ScoringFactors(1, 1, 1, 1, 1),
        rank=rank,
    )


def test_promote_within_band():
    store = LkgpStore(band=0.10)
    store.remember("standard:live_brief", "gemini", "m", now=1.0)
    ranked = (_t("groq", 1.0, 1), _t("gemini", 0.91, 2))
    out, promoted = store.promote(ranked, "standard:live_brief", now=2.0)
    assert promoted is True
    assert out[0].provider == "gemini"
    assert out[0].rank == 1
    assert out[1].provider == "groq"
    assert out[1].rank == 2


def test_no_promote_outside_band():
    store = LkgpStore(band=0.10)
    store.remember("k", "gemini", "m", now=1.0)
    ranked = (_t("groq", 1.0, 1), _t("gemini", 0.80, 2))
    out, promoted = store.promote(ranked, "k", now=2.0)
    assert promoted is False
    assert out[0].provider == "groq"


def test_forget_and_ttl():
    store = LkgpStore(band=0.10, ttl_s=10.0)
    store.remember("k", "gemini", "m", now=1.0)
    store.forget("k")
    assert store.get("k", now=2.0) is None
    store.remember("k", "gemini", "m", now=1.0)
    assert store.get("k", now=12.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_lkgp.py -v`

Expected: FAIL import error.

- [ ] **Step 3: Write `LkgpStore` + `RankedTarget`**

Append to `src/multiprovider_llm/routing/types.py`:

```python
@dataclass(frozen=True)
class RankedTarget:
    provider: str
    model: str
    score: float
    factors: ScoringFactors
    rank: int
```

(This must come *after* `ScoringFactors` in the same file.)

`src/multiprovider_llm/routing/lkgp.py`:

```python
from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import replace

from .types import RankedTarget


class LkgpStore:
    def __init__(self, *, band: float = 0.10, ttl_s: float | None = 1800.0) -> None:
        self._band = band
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        self._items: dict[str, tuple[str, str, float]] = {}

    def make_key(self, tier: str | None, task_kind: str | None) -> str:
        return f"{tier or '-'}:{task_kind or '-'}"

    def remember(
        self, key: str, provider: str, model: str, *, now: float | None = None
    ) -> None:
        clock = time.monotonic() if now is None else now
        with self._lock:
            self._items[key] = (provider, model, clock)

    def forget(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def get(self, key: str, *, now: float | None = None) -> tuple[str, str] | None:
        clock = time.monotonic() if now is None else now
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            provider, model, remembered_at = item
            if self._ttl_s is not None and clock - remembered_at >= self._ttl_s:
                self._items.pop(key, None)
                return None
            return (provider, model)

    def promote(
        self,
        ranked: Sequence[RankedTarget],
        key: str,
        *,
        now: float | None = None,
    ) -> tuple[tuple[RankedTarget, ...], bool]:
        remembered = self.get(key, now=now)
        if remembered is None or not ranked:
            return (tuple(ranked), False)
        provider, model = remembered
        best = ranked[0].score
        match_index = None
        for index, target in enumerate(ranked):
            if target.provider == provider and target.model == model:
                match_index = index
                break
        if match_index is None:
            return (tuple(ranked), False)
        chosen = ranked[match_index]
        if chosen.score < best * (1.0 - self._band):
            return (tuple(ranked), False)
        reordered = [chosen, *[t for i, t in enumerate(ranked) if i != match_index]]
        numbered = tuple(replace(target, rank=i) for i, target in enumerate(reordered, start=1))
        return (numbered, True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_lkgp.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/routing/lkgp.py src/multiprovider_llm/routing/types.py tests/test_lkgp.py
git commit -m "$(cat <<'EOF'
Add deterministic last-known-good promotion within a 10% band.

EOF
)"
```

---

### Task 10: `rank_candidates` — M4 contract

**Files:**
- Create: `src/multiprovider_llm/routing/rank.py`
- Modify: `src/multiprovider_llm/routing/types.py` (add `RoutingDiagnostics`, `RankingResult`)
- Modify: `src/multiprovider_llm/routing/__init__.py`
- Create: `tests/test_rank.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class RoutingDiagnostics:
    pool_size: int
    filtered_size: int
    ranked_targets: tuple[RankedTarget, ...]
    lkgp_promoted: bool
    filter_notes: tuple[FilterNote, ...]

@dataclass(frozen=True)
class RankingResult:
    ranked_targets: tuple[RankedTarget, ...]
    diagnostics: RoutingDiagnostics

def rank_candidates(
    candidates: Sequence[Candidate],
    *,
    tier: str | None,
    task_kind: str | None,
    lockout: ModelLockoutTracker,
    lkgp: LkgpStore,
    quota_reader: QuotaReader | None = None,
    cooldown_reader: CooldownReader | None = None,
    health_reader: HealthMetricsReader | None = None,
    known_adapters: frozenset[str] | None = None,
    weights: ScoringWeights | None = None,
    min_quota_pct: float = 0.05,
    now: float | None = None,
) -> RankingResult:
```

Algorithm:

1. `pool_size = len(candidates)`
2. `prefilter_candidates(...)` → eligible, notes
3. `filtered_size = len(eligible)`
4. Build `ScoringFactors` per eligible candidate; `constant = constant_factors_across(all factors)` (empty eligible → skip)
5. `score = calculate_score(...)`; sort by `(-score, provider, model)`; assign ranks 1..n
6. `lkgp.promote(ranked, lkgp.make_key(tier, task_kind), now=now)`
7. Return `RankingResult`

Empty eligible → empty `ranked_targets`, `lkgp_promoted=False`.

- [ ] **Step 1: Write the failing tests**

```python
import inspect

from multiprovider_llm.resilience.model_lockout import ModelLockoutTracker
from multiprovider_llm.routing.lkgp import LkgpStore
from multiprovider_llm.routing.rank import rank_candidates
from multiprovider_llm.routing.types import Candidate


def _c(provider, model, affinity, cost_tier="free"):
    return Candidate(
        provider=provider,
        model=model,
        adapter="openai_compat",
        base_url="https://example.test",
        cost_tier=cost_tier,
        freshness_ok=True,
        tier_affinity=affinity,
        http_referer=None,
    )


class Quota:
    def __init__(self, table):
        self.table = table

    def quota_remaining_pct(self, provider, model):
        return self.table.get((provider, model), 1.0)


def test_ranks_by_quota_and_tier_fit_not_input_order():
    groq = _c("groq", "8b", {"standard": 0.2})
    gemini = _c("gemini", "flash", {"standard": 1.0})
    result = rank_candidates(
        (groq, gemini),
        tier="standard",
        task_kind="live_brief",
        lockout=ModelLockoutTracker(),
        lkgp=LkgpStore(),
        quota_reader=Quota({("groq", "8b"): 0.1, ("gemini", "flash"): 0.9}),
    )
    assert [t.provider for t in result.ranked_targets] == ["gemini", "groq"]
    reversed_input = rank_candidates(
        (gemini, groq),
        tier="standard",
        task_kind="live_brief",
        lockout=ModelLockoutTracker(),
        lkgp=LkgpStore(),
        quota_reader=Quota({("groq", "8b"): 0.1, ("gemini", "flash"): 0.9}),
    )
    assert [t.provider for t in reversed_input.ranked_targets] == ["gemini", "groq"]
    assert result.diagnostics.pool_size == 2
    assert result.diagnostics.filtered_size == 2


def test_lockout_shows_in_diagnostics():
    lockout = ModelLockoutTracker()
    lockout.lock("groq", "8b", 30.0, now=1.0)
    result = rank_candidates(
        (_c("groq", "8b", {"standard": 1.0}), _c("gemini", "flash", {"standard": 1.0})),
        tier="standard",
        task_kind=None,
        lockout=lockout,
        lkgp=LkgpStore(),
        now=2.0,
    )
    assert [t.provider for t in result.ranked_targets] == ["gemini"]
    assert result.diagnostics.filter_notes[0].reason == "lockout"


def test_lkgp_promotion_recorded():
    store = LkgpStore(band=0.10)
    store.remember("standard:live_brief", "groq", "8b", now=1.0)
    result = rank_candidates(
        (
            _c("gemini", "flash", {"standard": 1.0}),
            _c("groq", "8b", {"standard": 1.0}),
        ),
        tier="standard",
        task_kind="live_brief",
        lockout=ModelLockoutTracker(),
        lkgp=store,
        quota_reader=Quota({("gemini", "flash"): 1.0, ("groq", "8b"): 0.95}),
        now=2.0,
    )
    assert result.diagnostics.lkgp_promoted is True
    assert result.ranked_targets[0].provider == "groq"


def test_rank_signature_forbids_policy_leaks():
    forbidden = {
        "tier_routing",
        "routing_prior",
        "provider_order",
        "preferred_providers",
        "prompt",
        "messages",
        "routing_mode",
        "monthly_tokens",
    }
    assert forbidden.isdisjoint(inspect.signature(rank_candidates).parameters)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rank.py -v`

Expected: FAIL import error.

- [ ] **Step 3: Implement `rank_candidates`**

Append to `src/multiprovider_llm/routing/types.py`:

```python
@dataclass(frozen=True)
class RoutingDiagnostics:
    pool_size: int
    filtered_size: int
    ranked_targets: tuple[RankedTarget, ...]
    lkgp_promoted: bool
    filter_notes: tuple[FilterNote, ...]


@dataclass(frozen=True)
class RankingResult:
    ranked_targets: tuple[RankedTarget, ...]
    diagnostics: RoutingDiagnostics
```

`src/multiprovider_llm/routing/rank.py`:

```python
from __future__ import annotations

from collections.abc import Sequence

from ..protocols import CooldownReader, HealthMetricsReader, QuotaReader
from ..resilience.model_lockout import ModelLockoutTracker
from .lkgp import LkgpStore
from .prefilter import prefilter_candidates
from .scoring import DEFAULT_WEIGHTS, calculate_score, constant_factors_across, factors_for
from .types import (
    Candidate,
    RankedTarget,
    RankingResult,
    RoutingDiagnostics,
    ScoringWeights,
)


def rank_candidates(
    candidates: Sequence[Candidate],
    *,
    tier: str | None,
    task_kind: str | None,
    lockout: ModelLockoutTracker,
    lkgp: LkgpStore,
    quota_reader: QuotaReader | None = None,
    cooldown_reader: CooldownReader | None = None,
    health_reader: HealthMetricsReader | None = None,
    known_adapters: frozenset[str] | None = None,
    weights: ScoringWeights | None = None,
    min_quota_pct: float = 0.05,
    now: float | None = None,
) -> RankingResult:
    used_weights = weights if weights is not None else DEFAULT_WEIGHTS
    pool_size = len(candidates)
    filtered = prefilter_candidates(
        candidates,
        lockout=lockout,
        quota_reader=quota_reader,
        cooldown_reader=cooldown_reader,
        known_adapters=known_adapters,
        min_quota_pct=min_quota_pct,
        now=now,
    )
    factor_rows = [
        factors_for(
            candidate,
            tier=tier,
            quota_reader=quota_reader,
            health_reader=health_reader,
        )
        for candidate in filtered.eligible
    ]
    constant = constant_factors_across(factor_rows)
    scored: list[RankedTarget] = []
    for candidate, factors in zip(filtered.eligible, factor_rows, strict=True):
        score = calculate_score(factors, used_weights, constant_factors=constant)
        scored.append(
            RankedTarget(
                provider=candidate.provider,
                model=candidate.model,
                score=score,
                factors=factors,
                rank=0,
            )
        )
    scored.sort(key=lambda target: (-target.score, target.provider, target.model))
    ranked = tuple(
        RankedTarget(
            provider=target.provider,
            model=target.model,
            score=target.score,
            factors=target.factors,
            rank=index,
        )
        for index, target in enumerate(scored, start=1)
    )
    ranked, promoted = lkgp.promote(
        ranked, lkgp.make_key(tier, task_kind), now=now
    )
    diagnostics = RoutingDiagnostics(
        pool_size=pool_size,
        filtered_size=len(filtered.eligible),
        ranked_targets=ranked,
        lkgp_promoted=promoted,
        filter_notes=filtered.notes,
    )
    return RankingResult(ranked_targets=ranked, diagnostics=diagnostics)
```

Replace `src/multiprovider_llm/routing/__init__.py` with:

```python
from .pool import build_candidate_pool, default_enabled_providers
from .rank import rank_candidates
from .types import Candidate, RankedTarget, RankingResult, RoutingDiagnostics

__all__ = [
    "Candidate",
    "RankedTarget",
    "RankingResult",
    "RoutingDiagnostics",
    "build_candidate_pool",
    "default_enabled_providers",
    "rank_candidates",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rank.py tests/test_scoring.py tests/test_lkgp.py tests/test_prefilter.py tests/test_pool.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/routing/rank.py src/multiprovider_llm/routing/types.py src/multiprovider_llm/routing/__init__.py tests/test_rank.py
git commit -m "$(cat <<'EOF'
Expose rank_candidates as the experimental M4 ranking contract.

EOF
)"
```

---

### Task 11: Freeze guards + full suite + STOP

**Files:**
- Create: `tests/test_smart_routing_freeze.py`
- Modify: `docs/proposals/2026-08-21-smart-routing-session-handoff.md` (add plan path; check the M1–M3 box only as “implementation plan written”, not “code shipped”, unless code is already committed by prior tasks)

**Interfaces:**
- Consumes: frozen `Client` / `AsyncClient`
- Produces: tests that fail if M4 or freeze regressions sneak in

- [ ] **Step 1: Write freeze tests**

```python
import inspect
from pathlib import Path

from multiprovider_llm.async_client import AsyncClient
from multiprovider_llm.client import Client
from multiprovider_llm.config import LibraryConfig


def test_client_complete_has_no_routing_mode():
    assert "routing_mode" not in inspect.signature(Client.complete).parameters
    assert "routing_mode" not in inspect.signature(AsyncClient.acomplete).parameters


def test_library_config_has_no_routing_mode():
    assert "routing_mode" not in LibraryConfig.__dataclass_fields__


def test_smart_client_module_does_not_exist():
    root = Path(__file__).resolve().parents[1] / "src" / "multiprovider_llm"
    assert not (root / "smart_client.py").exists()


def test_experimental_modules_do_not_mention_ain_tier_routing():
    root = Path(__file__).resolve().parents[1] / "src" / "multiprovider_llm"
    hits = []
    for path in list((root / "catalog").rglob("*.py")) + list((root / "routing").rglob("*.py")) + list(
        (root / "resilience").rglob("*.py")
    ):
        text = path.read_text(encoding="utf-8")
        for needle in ("tier_routing", "routing_mode", "routing_prior"):
            if needle in text:
                hits.append(f"{path.name}:{needle}")
    assert hits == []
```

- [ ] **Step 2: Run freeze tests (they should pass if prior tasks obeyed the constraints)**

Run: `python -m pytest tests/test_smart_routing_freeze.py -v`

Expected: PASS. If FAIL, delete the violating API — do not “fix” by implementing `SmartClient`.

- [ ] **Step 3: Run the full non-live suite**

Run: `python -m pytest -m "not live" -q`

Expected: all existing 0.1.0 tests still PASS; new M1–M3 tests PASS.

- [ ] **Step 4: Confirm stop conditions (no code in this step)**

All of the following must be true before declaring M1–M3 done:

1. `rank_candidates` returns `RankingResult` with `ranked_targets` + `RoutingDiagnostics`.
2. `Client.complete` / `AsyncClient.acomplete` signatures unchanged.
3. No `smart_client.py`.
4. No execute loop, no adapter dispatch from ranking modules.
5. Builtin catalog length in `20..30`.
6. D9 tests green.
7. `monthly_tokens` is not on `Candidate` and not a scoring input.

**STOP. Do not start M4.** The next human/architect step is review of `RankingResult` / `rank_candidates`. Only a new plan may implement `SmartClient`.

- [ ] **Step 5: Commit freeze tests**

```bash
git add tests/test_smart_routing_freeze.py docs/proposals/2026-08-21-smart-routing-session-handoff.md
git commit -m "$(cat <<'EOF'
Guard the 0.1.0 freeze against smart-routing API leakage.

EOF
)"
```

---

## Stop conditions (plan complete ≠ M4 authorized)

| Allowed after this plan | Forbidden |
| :--- | :--- |
| Catalog, pool, prefilter, lockout, classifier, scoring, LKGP, `rank_candidates` | `SmartClient`, `explain_last_route`, execute/fallback loop |
| Injected `QuotaReader` / `CooldownReader` / `HealthMetricsReader` | AIN `tier_routing` in scoring |
| Process-local metrics and lockout | Redis, disk lockout, TPM, named presets |
| Docs that point at this plan | Changing frozen `Client` |

M1–M3 **done** means: an architect can read `tests/test_rank.py` and `routing/rank.py` and decide whether M4 may be planned.

---

## Self-review (author)

1. **Spec coverage:** M1 catalog/pool → Tasks 1–3. M2 lockout/classifier/prefilter → Tasks 4–6. M3 scoring/LKGP/QuotaReader/`rank_candidates` → Tasks 7–10. Freeze/D9/no `routing_mode` → Tasks 3, 7, 10, 11. Constant-factor renormalization → Task 7. `freshness_required` as filter-only → Task 3. `monthly_tokens` static → Tasks 1, 3, 7. Catalog ~25 not 40 → Task 2. Artifact-store / hooks / json_schema / bandit / SmartClient → explicitly out of file map.
2. **Placeholders:** none remaining in task bodies.
3. **Type consistency:** `Candidate`, `ScoringFactors`, `ScoringWeights`, `RankedTarget`, `FilterNote`, `PrefilterResult`, `RoutingDiagnostics`, `RankingResult`, `FallbackDecision`, `ModelLockoutTracker`, `LkgpStore`, `RollingHealthMetrics`, `rank_candidates`, `build_candidate_pool` names are stable across tasks.
