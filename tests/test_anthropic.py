import json

import httpx
import pytest
import respx

from multiprovider_llm.errors import ProviderError
from multiprovider_llm.providers.anthropic import AnthropicAdapter
from multiprovider_llm.types import Message, ProviderRequest

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _req(**kwargs) -> ProviderRequest:
    defaults = dict(
        messages=(Message("user", "hi"),),
        model="claude-3-5-sonnet-20241022",
        timeout_s=10.0,
        response_format="text",
        json_schema=None,
        include_raw=False,
        extras={"temperature": 0.2, "max_tokens": 9, "model": "ignored"},
    )
    defaults.update(kwargs)
    return ProviderRequest(**defaults)


@respx.mock
def test_anthropic_messages_ok():
    route = respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "hello from claude"}],
                "usage": {"input_tokens": 4, "output_tokens": 6},
            },
        )
    )
    adapter = AnthropicAdapter(api_key="sk-ant-test")
    req = _req(
        messages=(Message("system", "be brief"), Message("user", "hi")),
    )
    resp = adapter.complete(req)
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "sk-ant-test"
    assert sent.headers["anthropic-version"] == "2023-06-01"
    assert sent.headers["content-type"].startswith("application/json")
    payload = json.loads(sent.content)
    assert payload["model"] == "claude-3-5-sonnet-20241022"
    assert payload["max_tokens"] == 1024
    assert payload["system"] == "be brief"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert "temperature" not in payload
    assert resp.text == "hello from claude"
    assert resp.usage.prompt_tokens == 4
    assert resp.usage.completion_tokens == 6
    assert resp.usage.total_tokens == 10
    assert resp.raw is None


@respx.mock
def test_anthropic_401_is_provider_error():
    respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})
    )
    adapter = AnthropicAdapter(api_key="bad")
    with pytest.raises(ProviderError) as ei:
        adapter.complete(_req())
    assert ei.value.status_code == 401
    assert ei.value.provider == "anthropic"
    assert len(ei.value.body) <= 500


@respx.mock
async def test_anthropic_acomplete_ok():
    respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "async ok"}]},
        )
    )
    adapter = AnthropicAdapter(api_key="sk-ant-test", base_url="https://api.anthropic.com")
    resp = await adapter.acomplete(_req(include_raw=True))
    assert resp.text == "async ok"
    assert resp.usage.prompt_tokens is None
    assert resp.raw is not None
    assert resp.raw["content"][0]["text"] == "async ok"
