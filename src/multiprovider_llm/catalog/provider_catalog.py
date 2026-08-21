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
