from __future__ import annotations

import httpx

from ..config import LibraryConfig
from ..errors import (
    BudgetExceeded,
    ConfigError,
    ProviderError,
    RateLimited,
    ValidationError,
)

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504, 529})


def resolve_chain(
    config: LibraryConfig,
    *,
    tier: str | None,
    provider_chain: tuple[str, ...] | None,
    freshness_required: bool,
) -> tuple[str, ...]:
    if provider_chain is not None:
        for name in provider_chain:
            if name not in config.providers:
                raise ConfigError(f"unknown provider in provider_chain: {name!r}")
        return _filter_names(config, provider_chain, freshness_required)

    base = _filter_names(config, config.provider_order, freshness_required)

    if tier is not None and tier in config.tier_routing:
        preferred = config.tier_routing[tier]
        base_set = set(base)
        lead = tuple(name for name in preferred if name in base_set)
        lead_set = set(lead)
        remainder = tuple(name for name in base if name not in lead_set)
        return lead + remainder

    return base


def resolve_model(config: LibraryConfig, provider: str, tier: str | None) -> str:
    provider_config = config.providers[provider]
    if tier is not None and tier in provider_config.models:
        return provider_config.models[tier]
    return provider_config.default_model


def is_auth_failure(exc: BaseException) -> bool:
    if isinstance(exc, ProviderError):
        return exc.status_code in {401, 403}
    return False


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (ValidationError, ConfigError, BudgetExceeded)):
        return False
    if isinstance(exc, RateLimited):
        return True
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, ProviderError):
        return exc.status_code in _RETRYABLE_STATUS_CODES
    return False


def _filter_names(
    config: LibraryConfig,
    names: tuple[str, ...],
    freshness_required: bool,
) -> tuple[str, ...]:
    chain: list[str] = []
    for name in names:
        provider = config.providers.get(name)
        if provider is None or not provider.enabled:
            continue
        if freshness_required and not provider.freshness_ok:
            continue
        chain.append(name)
    return tuple(chain)
