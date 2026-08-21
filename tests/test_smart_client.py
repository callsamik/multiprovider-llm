import inspect

import pytest

from multiprovider_llm.catalog import load_catalog_from_mapping
from multiprovider_llm.catalog.credentials import EnvCredentialResolver
from multiprovider_llm.errors import AllProvidersFailed, NoEligibleProviders, ProviderError
from multiprovider_llm.resilience.model_lockout import ModelLockoutTracker
from multiprovider_llm.routing.lkgp import LkgpStore
from multiprovider_llm.routing.metrics import RollingHealthMetrics
from multiprovider_llm.routing.types import Candidate
from multiprovider_llm.smart_client import SmartClient
from multiprovider_llm.types import AttemptRecord, CompletionResult, ProviderRequest, ProviderResponse, Usage


def _entry(**kw):
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
        "monthly_tokens": None,
        "pool_key": "gemini",
        "http_referer": None,
        "enabled_by_default": True,
    }
    row.update(kw)
    return row


def _catalog(*entries):
    return load_catalog_from_mapping({"catalog_id": "t", "entries": list(entries)})


def _creds(*envs):
    return EnvCredentialResolver({name: "k" for name in envs})


class FakeAdapter:
    def __init__(self, name, handler):
        self.name = name
        self.handler = handler
        self.requests: list[ProviderRequest] = []

    def complete(self, req: ProviderRequest) -> ProviderResponse:
        self.requests.append(req)
        return self.handler(req)

    async def acomplete(self, req: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError


class RecordingHooks:
    def __init__(self):
        self.attempts: list[AttemptRecord] = []
        self.successes: list[CompletionResult] = []
        self.failures: list[BaseException] = []

    def on_attempt(self, record: AttemptRecord) -> None:
        self.attempts.append(record)

    def on_success(self, result: CompletionResult) -> None:
        self.successes.append(result)

    def on_failure(self, error: BaseException, *, attempts: tuple[AttemptRecord, ...]) -> None:
        self.failures.append(error)


def _ok(text="ok"):
    def handler(_req):
        return ProviderResponse(text=text, usage=Usage(), status_code=200)

    return handler


def _raise(exc):
    def handler(_req):
        raise exc

    return handler


def _client(*, catalog, adapters, **kwargs):
    return SmartClient(
        catalog,
        credentials=kwargs.pop("credentials", _creds("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY")),
        adapters=adapters,
        **kwargs,
    )


def test_complete_has_no_provider_chain_or_routing_mode():
    params = inspect.signature(SmartClient.complete).parameters
    assert "provider_chain" not in params
    assert "routing_mode" not in params


def test_explain_last_route_none_before_complete():
    catalog = _catalog(_entry(), _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"))
    client = _client(catalog=catalog, adapters={})
    assert client.explain_last_route() is None


def test_happy_path_attempts_ranked_join_order_not_catalog_order():
    gemini = FakeAdapter("gemini", _ok("g"))
    groq = FakeAdapter("groq", _ok("q"))
    catalog = _catalog(
        _entry(),
        _entry(
            provider="groq",
            model="8b",
            adapter="openai_compat",
            api_key_env="GROQ_API_KEY",
            base_url="https://example.test/groq",
            tier_affinity={"standard": 0.2},
        ),
    )

    class Quota:
        def quota_remaining_pct(self, provider, model):
            return {("groq", "8b"): 0.1, ("gemini", "flash"): 0.9}[(provider, model)]

    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): gemini, ("groq", "8b"): groq},
        quota_reader=Quota(),
    )
    result = client.complete(prompt="hi", tier="standard")
    assert result.text == "g"
    assert result.provider == "gemini"
    assert result.model == "flash"
    assert groq.requests == []
    assert len(gemini.requests) == 1
    assert gemini.requests[0].model == "flash"
    diagnostics = client.explain_last_route()
    assert diagnostics is not None
    assert [t.provider for t in diagnostics.ranked_targets] == ["gemini", "groq"]


def test_classifier_fallback_on_429_tries_next_target():
    gemini = FakeAdapter(
        "gemini",
        _raise(ProviderError("hot", status_code=429, provider="gemini")),
    )
    groq = FakeAdapter("groq", _ok("rescued"))
    catalog = _catalog(
        _entry(),
        _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"),
    )
    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): gemini, ("groq", "8b"): groq},
    )
    result = client.complete(prompt="hi", tier="standard")
    assert result.text == "rescued"
    assert result.provider == "groq"
    assert len(gemini.requests) == 1
    assert len(groq.requests) == 1


def test_lockout_skips_429_pair_on_next_complete():
    lockout = ModelLockoutTracker()
    gemini = FakeAdapter(
        "gemini",
        _raise(ProviderError("hot", status_code=429, provider="gemini")),
    )
    groq = FakeAdapter("groq", _ok("ok"))
    catalog = _catalog(
        _entry(),
        _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"),
    )
    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): gemini, ("groq", "8b"): groq},
        lockout=lockout,
    )
    client.complete(prompt="hi", tier="standard")
    assert lockout.is_locked("gemini", "flash")
    gemini.requests.clear()
    groq.requests.clear()
    result = client.complete(prompt="hi", tier="standard")
    assert result.provider == "groq"
    assert gemini.requests == []
    notes = {n.reason for n in client.explain_last_route().filter_notes}
    assert "lockout" in notes


def test_json_validation_error_fallbacks_unlike_frozen_client():
    bad = FakeAdapter("gemini", _ok("not-json"))
    good = FakeAdapter("groq", _ok('{"ok": true}'))
    catalog = _catalog(
        _entry(),
        _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"),
    )
    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): bad, ("groq", "8b"): good},
    )
    result = client.complete(prompt="hi", tier="standard", response_format="json")
    assert result.provider == "groq"
    assert '"ok":true' in result.text.replace(" ", "")


def test_auth_stop_does_not_continue():
    gemini = FakeAdapter(
        "gemini",
        _raise(ProviderError("nope", status_code=401, provider="gemini")),
    )
    groq = FakeAdapter("groq", _ok("should-not-run"))
    catalog = _catalog(
        _entry(),
        _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"),
    )
    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): gemini, ("groq", "8b"): groq},
    )
    with pytest.raises(ProviderError):
        client.complete(prompt="hi", tier="standard", on_auth_failure="stop")
    assert groq.requests == []


def test_auth_continue_falls_back():
    gemini = FakeAdapter(
        "gemini",
        _raise(ProviderError("nope", status_code=401, provider="gemini")),
    )
    groq = FakeAdapter("groq", _ok("ok"))
    catalog = _catalog(
        _entry(),
        _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"),
    )
    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): gemini, ("groq", "8b"): groq},
    )
    result = client.complete(prompt="hi", tier="standard", on_auth_failure="continue")
    assert result.provider == "groq"


def test_empty_rank_raises_no_eligible_and_keeps_diagnostics():
    catalog = _catalog(_entry())
    lockout = ModelLockoutTracker()
    lockout.lock("gemini", "flash", 60.0)
    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): FakeAdapter("gemini", _ok())},
        lockout=lockout,
    )
    with pytest.raises(NoEligibleProviders):
        client.complete(prompt="hi", tier="standard")
    diagnostics = client.explain_last_route()
    assert diagnostics is not None
    assert diagnostics.filter_notes[0].reason == "lockout"


def test_exhaustion_raises_all_providers_failed_with_attempts():
    catalog = _catalog(
        _entry(),
        _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"),
    )
    client = _client(
        catalog=catalog,
        adapters={
            ("gemini", "flash"): FakeAdapter(
                "gemini", _raise(ProviderError("hot", status_code=429))
            ),
            ("groq", "8b"): FakeAdapter(
                "groq", _raise(ProviderError("hot", status_code=503))
            ),
        },
    )
    with pytest.raises(AllProvidersFailed) as exc:
        client.complete(prompt="hi", tier="standard")
    assert len(exc.value.attempts) == 2


def test_single_eligible_score_zero_is_still_attempted():
    gemini = FakeAdapter("gemini", _ok("only"))
    catalog = _catalog(_entry())
    client = _client(catalog=catalog, adapters={("gemini", "flash"): gemini})
    result = client.complete(prompt="hi", tier="standard")
    assert result.text == "only"
    assert len(gemini.requests) == 1
    ranked = client.explain_last_route().ranked_targets
    assert len(ranked) == 1
    assert ranked[0].score == 0.0


def test_lkgp_promotes_remembered_pair_on_next_complete():
    gemini = FakeAdapter("gemini", _ok("g"))
    groq = FakeAdapter("groq", _ok("q"))
    catalog = _catalog(
        _entry(),
        _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"),
    )
    lkgp = LkgpStore()
    lkgp.remember("standard:brief", "groq", "8b")
    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): gemini, ("groq", "8b"): groq},
        lkgp=lkgp,
    )
    result = client.complete(prompt="hi", tier="standard", task_kind="brief")
    assert result.provider == "groq"
    assert client.explain_last_route().lkgp_promoted is True


def test_lkgp_forgets_on_failure_of_remembered_pair():
    gemini = FakeAdapter("gemini", _ok("g"))
    groq = FakeAdapter("groq", _raise(ProviderError("hot", status_code=503)))
    catalog = _catalog(
        _entry(),
        _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"),
    )
    lkgp = LkgpStore()
    lkgp.remember("standard:brief", "groq", "8b")
    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): gemini, ("groq", "8b"): groq},
        lkgp=lkgp,
    )
    result = client.complete(prompt="hi", tier="standard", task_kind="brief")
    assert result.provider == "gemini"
    assert lkgp.get("standard:brief") == ("gemini", "flash")


def test_free_only_and_freshness_required_never_attempt_excluded():
    paid = FakeAdapter("openai", _ok("paid"))
    stale = FakeAdapter("ollama", _ok("stale"))
    gemini = FakeAdapter("gemini", _ok("free"))
    catalog = _catalog(
        _entry(),
        _entry(
            provider="openai",
            model="gpt-4o",
            adapter="openai_compat",
            api_key_env="OPENAI_API_KEY",
            cost_tier="paid",
            enabled_by_default=True,
        ),
        _entry(
            provider="ollama",
            model="llama3.2",
            adapter="openai_compat",
            auth="none",
            api_key_env=None,
            freshness_ok=False,
        ),
    )
    client = _client(
        catalog=catalog,
        credentials=_creds("GEMINI_API_KEY", "OPENAI_API_KEY"),
        adapters={
            ("gemini", "flash"): gemini,
            ("openai", "gpt-4o"): paid,
            ("ollama", "llama3.2"): stale,
        },
    )
    result = client.complete(prompt="hi", free_only=True, freshness_required=True)
    assert result.provider == "gemini"
    assert paid.requests == []
    assert stale.requests == []


def test_hooks_and_health_metrics_record_attempts():
    hooks = RecordingHooks()
    metrics = RollingHealthMetrics()
    gemini = FakeAdapter(
        "gemini",
        _raise(ProviderError("hot", status_code=429)),
    )
    groq = FakeAdapter("groq", _ok("ok"))
    catalog = _catalog(
        _entry(),
        _entry(provider="groq", model="8b", adapter="openai_compat", api_key_env="GROQ_API_KEY"),
    )
    client = _client(
        catalog=catalog,
        adapters={("gemini", "flash"): gemini, ("groq", "8b"): groq},
        hooks=hooks,
        metrics=metrics,
    )
    result = client.complete(prompt="hi", tier="standard")
    assert result.provider == "groq"
    assert len(hooks.attempts) == 2
    assert len(hooks.successes) == 1
    assert hooks.failures == []
    assert metrics.error_rate("gemini", "flash") == 1.0


def test_candidate_has_no_pool_key_field():
    assert "pool_key" not in Candidate.__dataclass_fields__
