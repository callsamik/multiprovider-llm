import httpx
import respx

from multiprovider_llm.providers.openai_compat import OpenAICompatAdapter
from multiprovider_llm.types import Message, ProviderRequest


@respx.mock
def test_openai_chat_completion_ok():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        )
    )
    adapter = OpenAICompatAdapter(api_key="sk-test", base_url="https://api.openai.com/v1")
    req = ProviderRequest(
        messages=(Message("user", "hi"),),
        model="gpt-4.1-mini",
        timeout_s=10.0,
        response_format="json",
        json_schema=None,
        include_raw=False,
        extras={},
    )
    resp = adapter.complete(req)
    assert route.called
    assert resp.text
    assert resp.usage.total_tokens == 3
    assert resp.raw is None


@respx.mock
def test_openai_include_raw_and_rate_limit():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate"}}, headers={"retry-after": "1"})
    )
    adapter = OpenAICompatAdapter(api_key="sk-test")
    req = ProviderRequest(
        messages=(Message("user", "hi"),),
        model="m",
        timeout_s=5.0,
        response_format="text",
        json_schema=None,
        include_raw=True,
        extras={},
    )
    import pytest
    from multiprovider_llm.errors import RateLimited

    with pytest.raises(RateLimited) as ei:
        adapter.complete(req)
    assert len(ei.value.body) <= 500
