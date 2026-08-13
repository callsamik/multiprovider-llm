import pytest

from multiprovider_llm.errors import ConfigError
from multiprovider_llm.providers import registry


def test_duplicate_registration_rejected():
    registry._clear_for_tests()
    registry.register_provider("openai", lambda: object())
    with pytest.raises(ConfigError):
        registry.register_provider("openai", lambda: object())
    registry.register_provider("openai", lambda: object(), replace=True)


def test_invalid_name_rejected():
    registry._clear_for_tests()
    with pytest.raises(ConfigError):
        registry.register_provider("bad name!", lambda: object())


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
