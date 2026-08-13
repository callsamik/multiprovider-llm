"""OpenAI-compatible Chat Completions adapter.

Reserved ``extras`` keys (must not be reinterpreted):
``model``, ``messages``, ``timeout_s``, ``response_format``, ``json_schema``.

Unknown extras keys are ignored.
"""

from __future__ import annotations

from typing import Any, Mapping

import httpx

from ..types import ProviderRequest, ProviderResponse, Usage
from .base import raise_for_status

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatAdapter:
    name: str

    def __init__(
        self,
        name: str = "openai",
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
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _payload(self, req: ProviderRequest) -> dict[str, Any]:
        # Ignore extras entirely: unknown keys are dropped; reserved keys
        # (model, messages, timeout_s, response_format, json_schema) stay on req.
        body: dict[str, Any] = {
            "model": req.model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        }
        if req.response_format == "json":
            body["response_format"] = {"type": "json_object"}
        return body

    def _parse(self, req: ProviderRequest, response: httpx.Response) -> ProviderResponse:
        raise_for_status(self.name, response)
        data: Mapping[str, Any] = response.json()
        choices = data.get("choices") or []
        text = ""
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            text = content if isinstance(content, str) else ""
        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens"),
            completion_tokens=usage_raw.get("completion_tokens"),
            total_tokens=usage_raw.get("total_tokens"),
        )
        return ProviderResponse(
            text=text,
            usage=usage,
            status_code=response.status_code,
            headers=dict(response.headers),
            raw=data if req.include_raw else None,
        )
