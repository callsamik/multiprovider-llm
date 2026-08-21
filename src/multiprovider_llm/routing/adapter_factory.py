"""Construct frozen adapters from a catalog Candidate.

Catalog provider names are not registry names. Dispatch uses
``Candidate.adapter`` only. ``http_referer`` is applied by an experimental
subclass so frozen adapter modules stay unchanged.
"""

from __future__ import annotations

from ..errors import ConfigError
from ..protocols import ProviderAdapter
from ..providers.anthropic import AnthropicAdapter
from ..providers.gemini import GeminiAdapter
from ..providers.openai_compat import OpenAICompatAdapter
from .types import Candidate


class OpenAICompatWithReferer(OpenAICompatAdapter):
    def __init__(
        self,
        name: str = "openai",
        *,
        api_key: str,
        base_url: str | None = None,
        http_referer: str,
    ) -> None:
        super().__init__(name, api_key=api_key, base_url=base_url)
        self._http_referer = http_referer

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers["HTTP-Referer"] = self._http_referer
        return headers


def adapter_for(candidate: Candidate, *, api_key: str) -> ProviderAdapter:
    name = candidate.provider
    base_url = candidate.base_url
    if candidate.adapter == "openai_compat":
        if candidate.http_referer:
            return OpenAICompatWithReferer(
                name,
                api_key=api_key,
                base_url=base_url,
                http_referer=candidate.http_referer,
            )
        return OpenAICompatAdapter(name, api_key=api_key, base_url=base_url)
    if candidate.adapter == "gemini":
        return GeminiAdapter(name, api_key=api_key, base_url=base_url)
    if candidate.adapter == "anthropic":
        return AnthropicAdapter(name, api_key=api_key, base_url=base_url)
    raise ConfigError(f"unknown adapter {candidate.adapter!r}")
