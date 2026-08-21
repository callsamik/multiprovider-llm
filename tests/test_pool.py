import inspect

from multiprovider_llm.catalog import load_catalog_from_mapping
from multiprovider_llm.catalog.credentials import EnvCredentialResolver
from multiprovider_llm.routing.pool import build_candidate_pool, default_enabled_providers


def _catalog():
    def e(**kw):
        row = {
            "provider": "gemini",
            "model": "flash",
            "display_name": "g",
            "adapter": "gemini",
            "auth": "api_key",
            "api_key_env": "GEMINI_API_KEY",
            "base_url": "https://example.test/gemini",
            "cost_tier": "free",
            "capabilities": {},
            "freshness_ok": True,
            "tier_affinity": {"standard": 1.0},
            "monthly_tokens": 9,
            "pool_key": None,
            "http_referer": None,
            "enabled_by_default": True,
        }
        row.update(kw)
        return row

    return load_catalog_from_mapping(
        {
            "catalog_id": "t",
            "entries": [
                e(),
                e(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY",
                  base_url="https://example.test/groq", enabled_by_default=True),
                e(provider="openai", model="gpt-4o", adapter="openai_compat", api_key_env="OPENAI_API_KEY",
                  base_url="https://example.test/openai", cost_tier="paid", enabled_by_default=False),
                e(provider="ollama", model="llama3.2", adapter="openai_compat", auth="none",
                  api_key_env=None, base_url="http://127.0.0.1:11434/v1", freshness_ok=False),
                e(provider="gemini", model="flash", display_name="dup"),  # duplicate pair
            ],
        }
    )


def test_pool_requires_credentials_except_auth_none():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier="standard", free_only=False, freshness_required=False
    )
    names = {(c.provider, c.model) for c in pool}
    assert ("gemini", "flash") in names
    assert ("ollama", "llama3.2") in names
    assert ("groq", "8b") not in names
    assert ("openai", "gpt-4o") not in names


def test_free_only_drops_paid():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x", "OPENAI_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=True, freshness_required=False
    )
    assert all(c.cost_tier == "free" for c in pool)
    assert ("openai", "gpt-4o") not in {(c.provider, c.model) for c in pool}


def test_freshness_required_drops_freshness_ok_false():
    catalog = _catalog()
    creds = EnvCredentialResolver({})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=False, freshness_required=True
    )
    assert ("ollama", "llama3.2") not in {(c.provider, c.model) for c in pool}


def test_enabled_providers_intersect():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x", "GROQ_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog,
        credentials=creds,
        tier=None,
        free_only=False,
        freshness_required=False,
        enabled_providers=frozenset({"gemini"}),
    )
    assert {(c.provider, c.model) for c in pool} == {("gemini", "flash")}


def test_default_enabled_providers_does_not_auto_apply():
    catalog = _catalog()
    creds = EnvCredentialResolver({"OPENAI_API_KEY": "x"})
    defaults = default_enabled_providers(catalog)
    assert "openai" not in defaults
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=False, freshness_required=False
    )
    assert ("openai", "gpt-4o") in {(c.provider, c.model) for c in pool}


def test_dedupe_first_wins():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=False, freshness_required=False
    )
    gemini = [c for c in pool if c.provider == "gemini" and c.model == "flash"]
    assert len(gemini) == 1
    assert gemini[0].base_url == "https://example.test/gemini"


def test_candidate_has_no_monthly_tokens():
    catalog = _catalog()
    creds = EnvCredentialResolver({"GEMINI_API_KEY": "x"})
    pool = build_candidate_pool(
        catalog, credentials=creds, tier=None, free_only=False, freshness_required=False
    )
    assert not hasattr(pool[0], "monthly_tokens")


def test_pool_signature_has_no_policy_leaks():
    forbidden = {
        "tier_routing",
        "routing_prior",
        "provider_order",
        "preferred_providers",
        "prompt",
        "messages",
        "routing_mode",
    }
    assert forbidden.isdisjoint(inspect.signature(build_candidate_pool).parameters)
