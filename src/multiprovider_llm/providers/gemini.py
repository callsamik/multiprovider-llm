"""Google Gemini generateContent adapter.

Reserved ``extras`` keys (must not be reinterpreted):
``model``, ``messages``, ``timeout_s``, ``response_format``, ``json_schema``.

Unknown extras keys are ignored.
"""

from __future__ import annotations

from typing import Any, Mapping

import httpx

from ..types import ProviderRequest, ProviderResponse, Usage
from .base import raise_for_status

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiAdapter:
    name: str

    def __init__(
        self,
        name: str = "gemini",
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
                self._url(req.model),
                params=self._params(),
                json=self._payload(req),
            )
        return self._parse(req, response)

    async def acomplete(self, req: ProviderRequest) -> ProviderResponse:
        async with httpx.AsyncClient(timeout=req.timeout_s) as client:
            response = await client.post(
                self._url(req.model),
                params=self._params(),
                json=self._payload(req),
            )
        return self._parse(req, response)

    def _url(self, model: str) -> str:
        return f"{self._base_url}/models/{model}:generateContent"

    def _params(self) -> dict[str, str]:
        return {"key": self._api_key}

    def _payload(self, req: ProviderRequest) -> dict[str, Any]:
        # Ignore extras entirely: unknown keys are dropped; reserved keys stay on req.
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in req.messages:
            if message.role == "system":
                system_parts.append(message.content)
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})
        if system_parts:
            prefix = "\n\n".join(system_parts)
            if contents and contents[0]["role"] == "user":
                contents[0]["parts"][0]["text"] = f"{prefix}\n\n{contents[0]['parts'][0]['text']}"
            else:
                contents.insert(0, {"role": "user", "parts": [{"text": prefix}]})
        return {"contents": contents}

    def _parse(self, req: ProviderRequest, response: httpx.Response) -> ProviderResponse:
        raise_for_status(self.name, response)
        data: Mapping[str, Any] = response.json()
        candidates = data.get("candidates") or []
        text = ""
        if candidates:
            parts = ((candidates[0].get("content") or {}).get("parts") or [])
            if parts:
                raw_text = parts[0].get("text")
                text = raw_text if isinstance(raw_text, str) else ""
        usage_raw = data.get("usageMetadata") or {}
        return ProviderResponse(
            text=text,
            usage=Usage(
                prompt_tokens=usage_raw.get("promptTokenCount"),
                completion_tokens=usage_raw.get("candidatesTokenCount"),
                total_tokens=usage_raw.get("totalTokenCount"),
            ),
            status_code=response.status_code,
            headers=dict(response.headers),
            raw=data if req.include_raw else None,
        )
