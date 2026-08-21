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
