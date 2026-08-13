from __future__ import annotations

from dataclasses import dataclass

from .limits import ProviderLimit


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
