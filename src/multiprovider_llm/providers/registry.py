"""Lazy provider factory registry.

Built-ins are registered without constructing adapters that need API keys.
When resolving via ``Client``, pass ``provider_config`` so ``base_url`` /
``api_key_env`` from config are applied.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

from ..config import ProviderConfig
from ..errors import ConfigError
from ..protocols import ProviderAdapter

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_factories: dict[str, Callable[..., Any]] = {}
_builtins_loaded = False

# Default env names when get_provider is called without ProviderConfig.
_DEFAULT_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def _clear_for_tests() -> None:
    global _builtins_loaded
    _factories.clear()
    _builtins_loaded = False


def resolve_api_key(api_key_env: str) -> str:
    """Resolve an API key from the environment.

    Empty ``api_key_env`` means no key required (e.g. some local servers) and
    returns ``\"\"``. A non-empty env name that is unset or blank raises
    ``ConfigError``.
    """
    name = (api_key_env or "").strip()
    if not name:
        return ""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"missing API key: environment variable {name!r} is not set or empty"
        )
    return value


def register_provider(
    name: str,
    factory: Callable[..., Any],
    *,
    replace: bool = False,
) -> None:
    if not _NAME_RE.fullmatch(name):
        raise ConfigError(f"invalid provider name: {name!r}")
    if name in _factories and not replace:
        raise ConfigError(f"provider already registered: {name}")
    _factories[name] = factory


def get_provider(
    name: str,
    *,
    provider_config: ProviderConfig | None = None,
) -> ProviderAdapter:
    ensure_builtins_loaded()
    factory = _factories.get(name)
    if factory is None:
        raise ConfigError(f"unknown provider: {name}")
    if provider_config is not None:
        return factory(provider_config)
    return factory(None)


def _openai_factory(provider_config: ProviderConfig | None = None) -> ProviderAdapter:
    from .openai_compat import OpenAICompatAdapter

    if provider_config is not None:
        return OpenAICompatAdapter(
            name=provider_config.name,
            api_key=resolve_api_key(provider_config.api_key_env),
            base_url=provider_config.base_url or None,
        )
    return OpenAICompatAdapter(api_key=resolve_api_key(_DEFAULT_API_KEY_ENV["openai"]))


def _anthropic_factory(provider_config: ProviderConfig | None = None) -> ProviderAdapter:
    from .anthropic import AnthropicAdapter

    if provider_config is not None:
        return AnthropicAdapter(
            name=provider_config.name,
            api_key=resolve_api_key(provider_config.api_key_env),
            base_url=provider_config.base_url or None,
        )
    return AnthropicAdapter(api_key=resolve_api_key(_DEFAULT_API_KEY_ENV["anthropic"]))


def _gemini_factory(provider_config: ProviderConfig | None = None) -> ProviderAdapter:
    from .gemini import GeminiAdapter

    if provider_config is not None:
        return GeminiAdapter(
            name=provider_config.name,
            api_key=resolve_api_key(provider_config.api_key_env),
            base_url=provider_config.base_url or None,
        )
    return GeminiAdapter(api_key=resolve_api_key(_DEFAULT_API_KEY_ENV["gemini"]))


def ensure_builtins_loaded() -> None:
    """Register built-in factories without constructing adapters."""
    global _builtins_loaded
    if _builtins_loaded:
        return
    from . import openai_compat as _openai_compat  # noqa: F401
    from . import anthropic as _anthropic  # noqa: F401
    from . import gemini as _gemini  # noqa: F401

    if "openai" not in _factories:
        register_provider("openai", _openai_factory)
    if "anthropic" not in _factories:
        register_provider("anthropic", _anthropic_factory)
    if "gemini" not in _factories:
        register_provider("gemini", _gemini_factory)
    _builtins_loaded = True
