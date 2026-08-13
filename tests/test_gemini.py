import json

import httpx
import pytest
import respx

from multiprovider_llm.errors import ProviderError
from multiprovider_llm.providers.gemini import GeminiAdapter
from multiprovider_llm.types import Message, ProviderRequest

MODEL = "gemini-1.5-flash"
GENERATE_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
)


def _req(**kwargs) -> ProviderRequest:
    defaults = dict(
        messages=(Message("user", "hi"),),
        model=MODEL,
        timeout_s=10.0,
        response_format="text",
        json_schema=None,
        include_raw=False,
        extras={"temperature": 0.2, "model": "ignored"},
    )
    defaults.update(kwargs)
    return ProviderRequest(**defaults)


@respx.mock
def test_gemini_generate_content_ok():
    route = respx.post(url__startswith=GENERATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "hello from gemini"}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 8,
                },
            },
        )
    )
    adapter = GeminiAdapter(api_key="gem-test")
    req = _req(
        messages=(
            Message("system", "be brief"),
            Message("user", "hi"),
            Message("assistant", "yo"),
            Message("user", "again"),
        ),
    )
    resp = adapter.complete(req)
    assert route.called
    sent = route.calls.last.request
    assert sent.url.params["key"] == "gem-test"
    payload = json.loads(sent.content)
    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][0]["parts"][0]["text"] == "be brief\n\nhi"
    assert payload["contents"][1] == {"role": "model", "parts": [{"text": "yo"}]}
    assert payload["contents"][2] == {"role": "user", "parts": [{"text": "again"}]}
    assert "temperature" not in payload
    assert resp.text == "hello from gemini"
    assert resp.usage.prompt_tokens == 3
    assert resp.usage.completion_tokens == 5
    assert resp.usage.total_tokens == 8
    assert resp.raw is None


@respx.mock
def test_gemini_401_is_provider_error():
    respx.post(url__startswith=GENERATE_URL).mock(
        return_value=httpx.Response(401, json={"error": {"message": "API key invalid"}})
    )
    adapter = GeminiAdapter(api_key="bad")
    with pytest.raises(ProviderError) as ei:
        adapter.complete(_req())
    assert ei.value.status_code == 401
    assert ei.value.provider == "gemini"
    assert len(ei.value.body) <= 500


@respx.mock
async def test_gemini_acomplete_ok():
    respx.post(url__startswith=GENERATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "async ok"}]}}]},
        )
    )
    adapter = GeminiAdapter(
        api_key="gem-test",
        base_url="https://generativelanguage.googleapis.com/v1beta",
    )
    resp = await adapter.acomplete(_req(include_raw=True))
    assert resp.text == "async ok"
    assert resp.usage.prompt_tokens is None
    assert resp.raw is not None
    assert resp.raw["candidates"][0]["content"]["parts"][0]["text"] == "async ok"
