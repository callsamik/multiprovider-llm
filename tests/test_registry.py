import pytest

from multiprovider_llm.errors import ConfigError
from multiprovider_llm.providers import registry


def test_duplicate_registration_rejected():
    registry._clear_for_tests()
    registry.register_provider("openai", lambda _cfg=None: object())
    with pytest.raises(ConfigError):
        registry.register_provider("openai", lambda _cfg=None: object())
    registry.register_provider("openai", lambda _cfg=None: object(), replace=True)


def test_invalid_name_rejected():
    registry._clear_for_tests()
    with pytest.raises(ConfigError):
        registry.register_provider("bad name!", lambda _cfg=None: object())


def test_builtins_register_anthropic_and_gemini(monkeypatch):
    registry._clear_for_tests()
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    openai = registry.get_provider("openai")
    anthropic = registry.get_provider("anthropic")
    gemini = registry.get_provider("gemini")
    assert openai.name == "openai"
    assert anthropic.name == "anthropic"
    assert gemini.name == "gemini"


def test_missing_api_key_raises_config_error(monkeypatch):
    registry._clear_for_tests()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        registry.get_provider("openai")


def test_empty_api_key_raises_config_error(monkeypatch):
    registry._clear_for_tests()
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        registry.get_provider("openai")


def test_empty_api_key_env_allows_blank_key():
    from multiprovider_llm.config import ProviderConfig

    registry._clear_for_tests()
    pcfg = ProviderConfig(
        name="openai",
        enabled=True,
        freshness_ok=True,
        models={"standard": "m"},
        default_model="m",
        base_url="http://localhost:11434/v1",
        api_key_env="",
    )
    adapter = registry.get_provider("openai", provider_config=pcfg)
    assert adapter._api_key == ""
    assert adapter._base_url == "http://localhost:11434/v1"
