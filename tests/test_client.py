import pytest
import httpx
import respx

from multiprovider_llm.client import Client
from multiprovider_llm.config import LibraryConfig, ProviderConfig, config_from_dict
from multiprovider_llm.errors import (
    AllProvidersFailed,
    BudgetExceeded,
    ConfigError,
    NoEligibleProviders,
    ProviderError,
    RateLimited,
    ValidationError,
)
from multiprovider_llm.limits import CooldownTracker, InMemoryLimiter, MemoryReservation, ProviderLimit
from multiprovider_llm.providers import registry
from multiprovider_llm.types import ProviderRequest, ProviderResponse, Usage


class FakeAdapter:
    def __init__(self, name: str, behavior):
        self.name = name
        self.behavior = behavior

    def complete(self, req: ProviderRequest) -> ProviderResponse:
        return self.behavior(req)

    async def acomplete(self, req: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError


def _config(order=("a", "b")):
    providers = {
        n: ProviderConfig(
            name=n,
            enabled=True,
            freshness_ok=True,
            models={"standard": "m"},
            default_model="m",
            base_url="",
            api_key_env="",
        )
        for n in order
    }
    return LibraryConfig(
        providers=providers,
        provider_order=order,
        tier_routing={},
        global_budget=None,
    )


def test_json_schema_requires_json_format():
    client = Client(_config(), adapters={})
    with pytest.raises(ValidationError):
        client.complete(prompt="x", response_format="text", json_schema={"type": "object"})


def test_no_eligible_providers():
    cfg = _config(order=("local",))
    cfg.providers["local"] = ProviderConfig(
        name="local",
        enabled=True,
        freshness_ok=False,
        models={},
        default_model="m",
        base_url="",
        api_key_env="",
    )
    client = Client(cfg, adapters={})
    with pytest.raises(NoEligibleProviders):
        client.complete(prompt="x", freshness_required=True)


def test_fallback_then_success():
    def fail(_req):
        raise RateLimited("no", status_code=429, provider="a")

    def ok(_req):
        return ProviderResponse(text='{"ok":true}', usage=Usage(total_tokens=1), status_code=200)

    client = Client(
        _config(("a", "b")),
        adapters={"a": FakeAdapter("a", fail), "b": FakeAdapter("b", ok)},
    )
    result = client.complete(prompt="hi", response_format="json")
    assert result.provider == "b"
    assert len(result.attempts) == 2
    assert result.attempts[0].ok is False and result.attempts[1].ok is True


def test_auth_stop_default_does_not_try_second():
    calls = []
    def auth(_req):
        calls.append("a")
        raise ProviderError("auth", status_code=401, provider="a")
    def ok(_req):
        calls.append("b")
        return ProviderResponse(text="y", usage=Usage(), status_code=200)
    client = Client(_config(("a", "b")), adapters={"a": FakeAdapter("a", auth), "b": FakeAdapter("b", ok)})
    with pytest.raises(ProviderError):
        client.complete(prompt="hi")
    assert calls == ["a"]


def test_auth_continue_falls_through():
    def auth(_req):
        raise ProviderError("auth", status_code=401, provider="a")
    def ok(_req):
        return ProviderResponse(text="y", usage=Usage(), status_code=200)
    client = Client(_config(("a", "b")), adapters={"a": FakeAdapter("a", auth), "b": FakeAdapter("b", ok)})
    result = client.complete(prompt="hi", on_auth_failure="continue")
    assert result.provider == "b"
    assert result.attempts[0].ok is False
    assert result.attempts[0].status_code == 401
    assert result.attempts[1].ok is True


def test_auth_continue_all_fail():
    def auth(req):
        raise ProviderError("auth", status_code=401)
    client = Client(_config(("a", "b")), adapters={"a": FakeAdapter("a", auth), "b": FakeAdapter("b", auth)})
    with pytest.raises(AllProvidersFailed) as ei:
        client.complete(prompt="hi", on_auth_failure="continue")
    assert len(ei.value.attempts) == 2


def test_auth_stops_chain():
    def auth(_req):
        raise ProviderError("auth", status_code=401, provider="a")

    def ok(_req):
        return ProviderResponse(text="y", usage=Usage(), status_code=200)

    client = Client(
        _config(("a", "b")),
        adapters={"a": FakeAdapter("a", auth), "b": FakeAdapter("b", ok)},
    )
    with pytest.raises(ProviderError):
        client.complete(prompt="hi")


def test_all_providers_cooling_raises_no_eligible():
    cooldowns = CooldownTracker()
    for name in ("a", "b"):
        cooldowns.set_cooldown(name, seconds=60.0)
    client = Client(_config(("a", "b")), cooldowns=cooldowns, adapters={})
    with pytest.raises(NoEligibleProviders):
        client.complete(prompt="hi")


def test_all_providers_failed():
    def fail(req):
        raise RateLimited("no", status_code=429)

    client = Client(
        _config(("a", "b")),
        adapters={"a": FakeAdapter("a", fail), "b": FakeAdapter("b", fail)},
    )
    with pytest.raises(AllProvidersFailed) as ei:
        client.complete(prompt="hi")
    assert len(ei.value.attempts) == 2


class _BudgetOnSecondReserve:
    """Limiter that admits the first reserve and raises BudgetExceeded on the next."""

    def __init__(self) -> None:
        self._count = 0

    def try_reserve(self, provider: str, *, tokens: int | None = None) -> MemoryReservation:
        self._count += 1
        if self._count >= 2:
            raise BudgetExceeded("global inflight budget exceeded")
        return MemoryReservation(provider=provider, token_estimate=tokens)

    def finalize(self, reservation, *, usage) -> None:
        del reservation, usage

    def release(self, reservation) -> None:
        del reservation


def test_complete_raises_budget_exceeded_on_second_reserve():
    def fail(_req):
        raise RateLimited("no", status_code=429, provider="a")

    def ok(_req):
        return ProviderResponse(text="y", usage=Usage(), status_code=200)

    client = Client(
        _config(("a", "b")),
        limiter=_BudgetOnSecondReserve(),
        adapters={"a": FakeAdapter("a", fail), "b": FakeAdapter("b", ok)},
    )
    with pytest.raises(BudgetExceeded):
        client.complete(prompt="hi")


def test_complete_raises_budget_exceeded_when_global_budget_held():
    limiter = InMemoryLimiter(
        per_provider={
            "a": ProviderLimit(max_inflight=4),
            "b": ProviderLimit(max_inflight=4),
        },
        global_budget=1,
    )
    held = limiter.try_reserve("a")

    def ok(_req):
        return ProviderResponse(text="y", usage=Usage(), status_code=200)

    client = Client(
        _config(("a", "b")),
        limiter=limiter,
        adapters={"a": FakeAdapter("a", ok), "b": FakeAdapter("b", ok)},
    )
    try:
        with pytest.raises(BudgetExceeded):
            client.complete(prompt="hi")
    finally:
        limiter.release(held)


@respx.mock
def test_client_uses_config_base_url_and_api_key_env(monkeypatch):
    """Builtin path must honor ProviderConfig.base_url and api_key_env."""
    registry._clear_for_tests()
    monkeypatch.setenv("CUSTOM_OPENAI_KEY", "sk-from-config")
    cfg = config_from_dict(
        {
            "providers": {
                "openai": {
                    "enabled": True,
                    "freshness_ok": True,
                    "models": {"standard": "gpt-test"},
                    "default_model": "gpt-test",
                    "base_url": "https://llm.example.test/v1",
                    "api_key_env": "CUSTOM_OPENAI_KEY",
                }
            },
            "provider_order": ["openai"],
        }
    )
    route = respx.post("https://llm.example.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "wired"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )
    )
    client = Client(cfg)
    result = client.complete(prompt="hi", provider_chain=["openai"])
    assert result.text == "wired"
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-from-config"


def test_client_missing_config_api_key_raises(monkeypatch):
    registry._clear_for_tests()
    monkeypatch.delenv("MISSING_KEY_FOR_TEST", raising=False)
    cfg = config_from_dict(
        {
            "providers": {
                "openai": {
                    "enabled": True,
                    "freshness_ok": True,
                    "models": {"standard": "gpt-test"},
                    "default_model": "gpt-test",
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "MISSING_KEY_FOR_TEST",
                }
            },
            "provider_order": ["openai"],
        }
    )
    client = Client(cfg)
    with pytest.raises(ConfigError, match="MISSING_KEY_FOR_TEST"):
        client.complete(prompt="hi")


def test_complete_passes_max_tokens_on_request():
    seen: list[ProviderRequest] = []

    def ok(req: ProviderRequest):
        seen.append(req)
        return ProviderResponse(text="y", usage=Usage(), status_code=200)

    client = Client(_config(("a",)), adapters={"a": FakeAdapter("a", ok)})
    client.complete(prompt="hi", max_tokens=4096)
    assert seen[0].max_tokens == 4096


def test_complete_rejects_non_positive_max_tokens():
    client = Client(_config(("a",)), adapters={"a": FakeAdapter("a", lambda r: None)})
    with pytest.raises(ValidationError, match="max_tokens"):
        client.complete(prompt="hi", max_tokens=0)


class RecordingHooks:
    def __init__(self):
        self.attempts = []
        self.successes = []

    def on_attempt(self, record):
        self.attempts.append(record)
        raise RuntimeError("hook blowup")

    def on_success(self, result):
        self.successes.append(result)

    def on_failure(self, error, *, attempts):
        pass


def test_hooks_swallowed_on_success():
    hooks = RecordingHooks()

    def ok(_req):
        return ProviderResponse(text="y", usage=Usage(), status_code=200)

    client = Client(
        _config(("a",)),
        adapters={"a": FakeAdapter("a", ok)},
        hooks=hooks,
    )
    result = client.complete(prompt="hi")
    assert result.text
    assert hooks.successes
