from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .limits import ProviderLimit

_PROVIDER_FIELDS = frozenset(
    {
        "enabled",
        "freshness_ok",
        "models",
        "default_model",
        "base_url",
        "api_key_env",
        "rate_limits",
    }
)
_TOP_LEVEL_FIELDS = frozenset({"providers", "provider_order", "tier_routing", "global_budget"})


@dataclass
class ProviderConfig:
    name: str
    enabled: bool
    freshness_ok: bool
    models: dict[str, str]
    default_model: str
    base_url: str
    api_key_env: str
    rate_limits: ProviderLimit | None = None


@dataclass
class LibraryConfig:
    providers: dict[str, ProviderConfig]
    provider_order: tuple[str, ...]
    tier_routing: dict[str, tuple[str, ...]]
    global_budget: int | None = None


def _require_mapping(data: Mapping, *, field: str) -> Mapping:
    value = data.get(field)
    if value is None:
        raise ConfigError(f"missing required field: {field!r}")
    if not isinstance(value, Mapping):
        raise ConfigError(f"{field!r} must be a mapping")
    return value


def _require_str(data: Mapping, *, field: str, context: str) -> str:
    value = data.get(field)
    if value is None:
        raise ConfigError(f"missing required field {field!r} in {context}")
    if not isinstance(value, str):
        raise ConfigError(f"{field!r} in {context} must be a string")
    return value


def _require_bool(data: Mapping, *, field: str, context: str) -> bool:
    value = data.get(field)
    if value is None:
        raise ConfigError(f"missing required field {field!r} in {context}")
    if not isinstance(value, bool):
        raise ConfigError(f"{field!r} in {context} must be a boolean")
    return value


def _parse_rate_limits(raw: object, *, context: str) -> ProviderLimit:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"rate_limits in {context} must be a mapping")
    unknown = set(raw) - {"max_inflight"}
    if unknown:
        raise ConfigError(f"unknown rate_limits keys in {context}: {sorted(unknown)!r}")
    max_inflight = raw.get("max_inflight")
    if max_inflight is None:
        raise ConfigError(f"missing required field 'max_inflight' in rate_limits for {context}")
    if not isinstance(max_inflight, int) or isinstance(max_inflight, bool):
        raise ConfigError(f"max_inflight in {context} must be an integer")
    return ProviderLimit(max_inflight=max_inflight)


def _parse_provider(name: str, raw: object) -> ProviderConfig:
    context = f"providers[{name!r}]"
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{context} must be a mapping")
    unknown = set(raw) - _PROVIDER_FIELDS
    if unknown:
        raise ConfigError(f"unknown keys in {context}: {sorted(unknown)!r}")
    models_raw = raw.get("models")
    if models_raw is None:
        raise ConfigError(f"missing required field 'models' in {context}")
    if not isinstance(models_raw, Mapping):
        raise ConfigError(f"models in {context} must be a mapping")
    models: dict[str, str] = {}
    for tier, model in models_raw.items():
        if not isinstance(tier, str) or not isinstance(model, str):
            raise ConfigError(f"models in {context} must map tier names to model strings")
        models[tier] = model
    rate_limits = None
    if "rate_limits" in raw:
        rate_limits = _parse_rate_limits(raw["rate_limits"], context=context)
    return ProviderConfig(
        name=name,
        enabled=_require_bool(raw, field="enabled", context=context),
        freshness_ok=_require_bool(raw, field="freshness_ok", context=context),
        models=models,
        default_model=_require_str(raw, field="default_model", context=context),
        base_url=_require_str(raw, field="base_url", context=context),
        api_key_env=_require_str(raw, field="api_key_env", context=context),
        rate_limits=rate_limits,
    )


def _parse_provider_order(raw: object, *, known: set[str]) -> tuple[str, ...]:
    if raw is None:
        raise ConfigError("missing required field: 'provider_order'")
    if not isinstance(raw, list):
        raise ConfigError("provider_order must be a list")
    order: list[str] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, str):
            raise ConfigError(f"provider_order[{idx}] must be a string")
        if item not in known:
            raise ConfigError(f"provider_order references unknown provider: {item!r}")
        order.append(item)
    return tuple(order)


def _parse_tier_routing(raw: object, *, known: set[str]) -> dict[str, tuple[str, ...]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ConfigError("tier_routing must be a mapping")
    routing: dict[str, tuple[str, ...]] = {}
    for tier, providers in raw.items():
        if not isinstance(tier, str):
            raise ConfigError("tier_routing keys must be strings")
        if not isinstance(providers, list):
            raise ConfigError(f"tier_routing[{tier!r}] must be a list")
        chain: list[str] = []
        for idx, name in enumerate(providers):
            if not isinstance(name, str):
                raise ConfigError(f"tier_routing[{tier!r}][{idx}] must be a string")
            if name not in known:
                raise ConfigError(
                    f"tier_routing[{tier!r}] references unknown provider: {name!r}"
                )
            chain.append(name)
        routing[tier] = tuple(chain)
    return routing


def config_from_dict(data: Mapping) -> LibraryConfig:
    unknown = set(data) - _TOP_LEVEL_FIELDS
    if unknown:
        raise ConfigError(f"unknown top-level config keys: {sorted(unknown)!r}")

    providers_raw = _require_mapping(data, field="providers")
    providers: dict[str, ProviderConfig] = {}
    for name, raw in providers_raw.items():
        if not isinstance(name, str):
            raise ConfigError("provider names must be strings")
        providers[name] = _parse_provider(name, raw)

    known = set(providers)
    provider_order = _parse_provider_order(data.get("provider_order"), known=known)
    tier_routing = _parse_tier_routing(data.get("tier_routing"), known=known)

    global_budget = data.get("global_budget")
    if global_budget is not None and (
        not isinstance(global_budget, int) or isinstance(global_budget, bool)
    ):
        raise ConfigError("global_budget must be an integer or null")

    return LibraryConfig(
        providers=providers,
        provider_order=provider_order,
        tier_routing=tier_routing,
        global_budget=global_budget,
    )


def load_config(path: str | Path) -> LibraryConfig:
    config_path = Path(path)
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {config_path}: {exc}") from exc
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in config file {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config file {config_path} must contain a JSON object")
    return config_from_dict(data)
