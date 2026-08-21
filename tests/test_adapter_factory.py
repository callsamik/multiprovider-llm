from multiprovider_llm.providers.anthropic import AnthropicAdapter
from multiprovider_llm.providers.gemini import GeminiAdapter
from multiprovider_llm.providers.openai_compat import OpenAICompatAdapter
from multiprovider_llm.routing.adapter_factory import adapter_for
from multiprovider_llm.routing.types import Candidate


def _candidate(**kw):
    row = dict(
        provider="groq",
        model="8b",
        adapter="openai_compat",
        base_url="https://example.test/groq",
        cost_tier="free",
        freshness_ok=True,
        tier_affinity={"standard": 1.0},
        http_referer=None,
    )
    row.update(kw)
    return Candidate(**row)


def test_openai_compat_uses_candidate_name_and_base_url():
    adapter = adapter_for(_candidate(), api_key="k")
    assert isinstance(adapter, OpenAICompatAdapter)
    assert adapter.name == "groq"
    assert adapter._base_url == "https://example.test/groq"


def test_referer_header_added_without_changing_frozen_adapter_module():
    adapter = adapter_for(_candidate(http_referer="https://localhost"), api_key="k")
    headers = adapter._headers()
    assert headers["HTTP-Referer"] == "https://localhost"
    assert type(adapter) is not OpenAICompatAdapter


def test_gemini_and_anthropic_kinds():
    gemini = adapter_for(
        _candidate(provider="gemini", adapter="gemini", base_url="https://example.test/g"),
        api_key="k",
    )
    anthropic = adapter_for(
        _candidate(provider="anthropic", adapter="anthropic", base_url="https://example.test/a"),
        api_key="k",
    )
    assert isinstance(gemini, GeminiAdapter)
    assert gemini.name == "gemini"
    assert isinstance(anthropic, AnthropicAdapter)
    assert anthropic.name == "anthropic"
