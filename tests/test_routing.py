import pytest

from multiprovider_llm.config import LibraryConfig, ProviderConfig
from multiprovider_llm.errors import ConfigError, ProviderError, RateLimited, ValidationError
from multiprovider_llm.routing import is_retryable, resolve_chain, resolve_model


def _cfg():
    return LibraryConfig(
        providers={
            "openai": ProviderConfig(
                name="openai",
                enabled=True,
                freshness_ok=True,
                models={"simple": "gpt-small", "standard": "gpt-mid", "complex": "gpt-big"},
                default_model="gpt-mid",
                base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
            "ollama": ProviderConfig(
                name="ollama",
                enabled=True,
                freshness_ok=False,
                models={},
                default_model="qwen",
                base_url="http://localhost:11434/v1",
                api_key_env="",
            ),
            "anthropic": ProviderConfig(
                name="anthropic",
                enabled=True,
                freshness_ok=True,
                models={"standard": "claude"},
                default_model="claude",
                base_url="https://api.anthropic.com",
                api_key_env="ANTHROPIC_API_KEY",
            ),
        },
        provider_order=("openai", "anthropic", "ollama"),
        tier_routing={"standard": ("anthropic", "openai")},
        global_budget=None,
    )


def test_explicit_chain_overrides_tier():
    chain = resolve_chain(
        _cfg(), tier="standard", provider_chain=("openai",), freshness_required=False
    )
    assert chain == ("openai",)


def test_explicit_chain_unknown_provider_raises():
    with pytest.raises(ConfigError, match="unknown provider"):
        resolve_chain(
            _cfg(),
            tier=None,
            provider_chain=("openai", "not_a_provider"),
            freshness_required=False,
        )


def test_tier_routing_reorders():
    chain = resolve_chain(_cfg(), tier="standard", provider_chain=None, freshness_required=False)
    assert chain[0] == "anthropic"
    assert "openai" in chain


def test_freshness_filters_local():
    chain = resolve_chain(_cfg(), tier=None, provider_chain=None, freshness_required=True)
    assert "ollama" not in chain


def test_retryability_matrix():
    assert is_retryable(RateLimited("x", status_code=429))
    assert is_retryable(ProviderError("x", status_code=503))
    assert is_retryable(ProviderError("x", status_code=529))  # Anthropic overloaded
    assert not is_retryable(ProviderError("x", status_code=401))
    assert not is_retryable(ValidationError("bad"))


def test_resolve_model_tier_hit():
    assert resolve_model(_cfg(), "openai", "simple") == "gpt-small"
    assert resolve_model(_cfg(), "openai", "standard") == "gpt-mid"
    assert resolve_model(_cfg(), "openai", "complex") == "gpt-big"


def test_resolve_model_default_fallback():
    assert resolve_model(_cfg(), "openai", None) == "gpt-mid"
    assert resolve_model(_cfg(), "openai", "missing-tier") == "gpt-mid"
    assert resolve_model(_cfg(), "ollama", "standard") == "qwen"
