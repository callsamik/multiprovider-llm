"""Anthropic Messages API adapter.

Reserved ``extras`` keys (must not be reinterpreted):
``model``, ``messages``, ``timeout_s``, ``response_format``, ``json_schema``,
``max_tokens``.

Unknown extras keys are ignored. ``max_tokens`` comes from
``ProviderRequest.max_tokens`` (default ``DEFAULT_MAX_TOKENS`` when unset).
"""

from __future__ import annotations

from typing import Any, Mapping

import httpx

from ..types import ProviderRequest, ProviderResponse, Usage
from .base import raise_for_status

DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024


class AnthropicAdapter:
    name: str

    def __init__(
        self,
        name: str = "anthropic",
        *,
        api_key: str,
        base_url: str | None = None,
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    def complete(self, req: ProviderRequest) -> ProviderResponse:
        with httpx.Client(timeout=req.timeout_s) as client:
            response = client.post(
                self._url(),
                headers=self._headers(),
                json=self._payload(req),
            )
        return self._parse(req, response)

    async def acomplete(self, req: ProviderRequest) -> ProviderResponse:
        async with httpx.AsyncClient(timeout=req.timeout_s) as client:
            response = await client.post(
                self._url(),
                headers=self._headers(),
                json=self._payload(req),
            )
        return self._parse(req, response)

    def _url(self) -> str:
        return f"{self._base_url}/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _payload(self, req: ProviderRequest) -> dict[str, Any]:
        # Ignore extras entirely: unknown keys are dropped; reserved keys
        # stay on req. max_tokens comes from ProviderRequest.max_tokens.
        messages = list(req.messages)
        system: str | None = None
        if messages and messages[0].role == "system":
            system = messages[0].content
            messages = messages[1:]
        body: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens if req.max_tokens is not None else DEFAULT_MAX_TOKENS,
            "messages": [
                {
                    "role": m.role if m.role in {"user", "assistant"} else "user",
                    "content": m.content,
                }
                for m in messages
            ],
        }
        if system is not None:
            body["system"] = system
        return body

    def _parse(self, req: ProviderRequest, response: httpx.Response) -> ProviderResponse:
        raise_for_status(self.name, response)
        data: Mapping[str, Any] = response.json()
        content = data.get("content") or []
        text = ""
        if content:
            first = content[0] or {}
            raw_text = first.get("text")
            text = raw_text if isinstance(raw_text, str) else ""
        usage_raw = data.get("usage") or {}
        prompt = usage_raw.get("input_tokens")
        completion = usage_raw.get("output_tokens")
        total = prompt + completion if prompt is not None and completion is not None else None
        return ProviderResponse(
            text=text,
            usage=Usage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
            ),
            status_code=response.status_code,
            headers=dict(response.headers),
            raw=data if req.include_raw else None,
        )
