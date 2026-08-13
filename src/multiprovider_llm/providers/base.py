"""Shared HTTP helpers for provider adapters.

Reserved ``extras`` keys (adapters must not reinterpret):
``model``, ``messages``, ``timeout_s``, ``response_format``, ``json_schema``.

Unknown extras keys are ignored.
"""

from __future__ import annotations

import httpx

from ..errors import ProviderError, RateLimited

DEFAULT_BODY_LIMIT = 500


def truncate_body(text: str, limit: int = DEFAULT_BODY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def raise_for_status(provider: str, response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    body = truncate_body(response.text or "")
    headers = dict(response.headers)
    if response.status_code == 429:
        raise RateLimited(
            f"{provider} rate limited",
            status_code=429,
            headers=headers,
            body=body,
            provider=provider,
        )
    raise ProviderError(
        f"{provider} HTTP {response.status_code}",
        status_code=response.status_code,
        headers=headers,
        body=body,
        provider=provider,
    )
