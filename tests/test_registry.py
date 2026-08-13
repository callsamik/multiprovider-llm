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
