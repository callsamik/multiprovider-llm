import json
from pathlib import Path

import pytest

from multiprovider_llm.config import config_from_dict, load_config
from multiprovider_llm.errors import ConfigError
from multiprovider_llm.limits import ProviderLimit


def _minimal_dict(*, include_optional: bool = True) -> dict:
    data = {
        "providers": {
            "openai": {
                "enabled": True,
                "freshness_ok": True,
                "models": {"standard": "gpt-4o-mini"},
                "default_model": "gpt-4o-mini",
                "base_url": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
            },
            "anthropic": {
                "enabled": True,
                "freshness_ok": True,
                "models": {"standard": "claude-3-5-sonnet"},
                "default_model": "claude-3-5-sonnet",
                "base_url": "https://api.anthropic.com",
                "api_key_env": "ANTHROPIC_API_KEY",
            },
            "gemini": {
                "enabled": True,
                "freshness_ok": True,
                "models": {"standard": "gemini-2.0-flash"},
                "default_model": "gemini-2.0-flash",
                "base_url": "https://generativelanguage.googleapis.com",
                "api_key_env": "GEMINI_API_KEY",
            },
        },
        "provider_order": ["openai", "anthropic", "gemini"],
    }
    if include_optional:
        data["tier_routing"] = {"standard": ["anthropic", "openai"]}
        data["global_budget"] = 8
        data["providers"]["openai"]["rate_limits"] = {
            "max_inflight": 4,
        }
    return data


def test_config_from_dict_minimal():
    cfg = config_from_dict(_minimal_dict())
    assert tuple(cfg.provider_order) == ("openai", "anthropic", "gemini")
    assert cfg.tier_routing["standard"] == ("anthropic", "openai")
    assert cfg.global_budget == 8
    openai = cfg.providers["openai"]
    assert openai.name == "openai"
    assert openai.enabled is True
    assert openai.api_key_env == "OPENAI_API_KEY"
    assert openai.rate_limits == ProviderLimit(max_inflight=4)
    assert cfg.providers["gemini"].api_key_env == "GEMINI_API_KEY"
    assert not hasattr(ProviderLimit(max_inflight=1), "max_tokens_per_minute")


def test_max_tokens_per_minute_rejected_as_unknown():
    """0.1.0 honesty: do not advertise unenforced TPM via public config."""
    data = _minimal_dict(include_optional=False)
    data["providers"]["openai"]["rate_limits"] = {
        "max_inflight": 2,
        "max_tokens_per_minute": 100000,
    }
    with pytest.raises(ConfigError, match="max_tokens_per_minute"):
        config_from_dict(data)


def test_load_config_from_json_file(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_minimal_dict()), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.providers["anthropic"].default_model == "claude-3-5-sonnet"
    assert "gemini" in cfg.providers


def test_missing_providers_raises():
    data = _minimal_dict(include_optional=False)
    del data["providers"]
    with pytest.raises(ConfigError, match="providers"):
        config_from_dict(data)


def test_missing_provider_field_raises():
    data = _minimal_dict(include_optional=False)
    del data["providers"]["openai"]["default_model"]
    with pytest.raises(ConfigError, match="default_model"):
        config_from_dict(data)


def test_unknown_top_level_key_raises():
    data = _minimal_dict(include_optional=False)
    data["extra"] = True
    with pytest.raises(ConfigError, match="unknown"):
        config_from_dict(data)


def test_provider_order_unknown_provider_raises():
    data = _minimal_dict(include_optional=False)
    data["provider_order"] = ["openai", "missing"]
    with pytest.raises(ConfigError, match="missing"):
        config_from_dict(data)
