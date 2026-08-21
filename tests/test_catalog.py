import pytest

from multiprovider_llm.catalog import ProviderCatalogEntry, load_catalog_from_mapping
from multiprovider_llm.errors import ConfigError


def _entry(**overrides):
    base = {
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "display_name": "Gemini Flash",
        "adapter": "gemini",
        "auth": "api_key",
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "cost_tier": "free",
        "capabilities": {},
        "freshness_ok": True,
        "tier_affinity": {"simple": 0.7, "standard": 1.0, "complex": 0.8},
        "monthly_tokens": 1_000_000,
        "pool_key": None,
        "http_referer": None,
        "enabled_by_default": True,
    }
    base.update(overrides)
    return base


def test_load_catalog_from_mapping_round_trip():
    catalog = load_catalog_from_mapping(
        {"catalog_id": "test:v1", "entries": [_entry()]}
    )
    assert catalog.catalog_id == "test:v1"
    assert len(catalog.entries) == 1
    e = catalog.entries[0]
    assert isinstance(e, ProviderCatalogEntry)
    assert e.provider == "gemini"
    assert e.cost_tier == "free"
    assert e.monthly_tokens == 1_000_000
    assert e.tier_affinity["standard"] == 1.0


def test_unknown_entry_key_raises():
    with pytest.raises(ConfigError, match="unknown"):
        load_catalog_from_mapping(
            {"catalog_id": "t", "entries": [_entry(ain_tier_routing=["groq"])]}
        )


def test_invalid_adapter_raises():
    with pytest.raises(ConfigError, match="adapter"):
        load_catalog_from_mapping(
            {"catalog_id": "t", "entries": [_entry(adapter="groq_preset")]}
        )


def test_auth_none_allows_null_api_key_env():
    catalog = load_catalog_from_mapping(
        {
            "catalog_id": "t",
            "entries": [
                _entry(
                    provider="ollama",
                    model="llama3.2",
                    adapter="openai_compat",
                    auth="none",
                    api_key_env=None,
                    base_url="http://127.0.0.1:11434/v1",
                    freshness_ok=False,
                    monthly_tokens=None,
                )
            ],
        }
    )
    assert catalog.entries[0].auth == "none"
    assert catalog.entries[0].api_key_env is None


def test_affinity_out_of_range_raises():
    with pytest.raises(ConfigError, match="tier_affinity"):
        load_catalog_from_mapping(
            {"catalog_id": "t", "entries": [_entry(tier_affinity={"standard": 1.5})]}
        )
