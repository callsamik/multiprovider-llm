import pytest

from multiprovider_llm.client import Client
from multiprovider_llm.config import LibraryConfig, ProviderConfig
from multiprovider_llm.errors import (
    AllProvidersFailed,
    NoEligibleProviders,
    ProviderError,
    RateLimited,
    ValidationError,
)
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
