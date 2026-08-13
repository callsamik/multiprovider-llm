"""Lazy provider factory registry.

Built-ins are registered without constructing adapters that need API keys.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

from ..errors import ConfigError
from ..protocols import ProviderAdapter

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_factories: dict[str, Callable[[], Any]] = {}
_builtins_loaded = False


def _clear_for_tests() -> None:
    global _builtins_loaded
    _factories.clear()
    _builtins_loaded = False


def register_provider(
    name: str,
    factory: Callable[[], Any],
    *,
    replace: bool = False,
) -> None:
    if not _NAME_RE.fullmatch(name):
        raise ConfigError(f"invalid provider name: {name!r}")
    if name in _factories and not replace:
        raise ConfigError(f"provider already registered: {name}")
    _factories[name] = factory


def get_provider(name: str) -> ProviderAdapter:
    ensure_builtins_loaded()
    factory = _factories.get(name)
    if factory is None:
        raise ConfigError(f"unknown provider: {name}")
    return factory()


def _openai_factory() -> ProviderAdapter:
    from .openai_compat import OpenAICompatAdapter

    return OpenAICompatAdapter(api_key=os.environ.get("OPENAI_API_KEY", ""))


def _anthropic_factory() -> ProviderAdapter:
    from .anthropic import AnthropicAdapter

    return AnthropicAdapter(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


def _gemini_factory() -> ProviderAdapter:
    from .gemini import GeminiAdapter

    return GeminiAdapter(api_key=os.environ.get("GEMINI_API_KEY", ""))


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
