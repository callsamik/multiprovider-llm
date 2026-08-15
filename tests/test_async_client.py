import asyncio

import pytest

from multiprovider_llm.async_client import AsyncClient
from multiprovider_llm.config import LibraryConfig, ProviderConfig
from multiprovider_llm.errors import (
    AllProvidersFailed,
    NoEligibleProviders,
    ProviderError,
    RateLimited,
    ValidationError,
)
from multiprovider_llm.limits import CooldownTracker, InMemoryLimiter, ProviderLimit
from multiprovider_llm.types import CompletionResult, ProviderRequest, ProviderResponse, Usage


class FakeAsyncAdapter:
    def __init__(self, name: str, behavior):
        self.name = name
        self.behavior = behavior

    def complete(self, req: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    async def acomplete(self, req: ProviderRequest) -> ProviderResponse:
        return await self.behavior(req)


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


async def test_json_schema_requires_json_format():
    client = AsyncClient(_config(), adapters={})
    with pytest.raises(ValidationError):
        await client.acomplete(prompt="x", response_format="text", json_schema={"type": "object"})


async def test_no_eligible_providers():
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
    client = AsyncClient(cfg, adapters={})
    with pytest.raises(NoEligibleProviders):
        await client.acomplete(prompt="x", freshness_required=True)


async def test_fallback_then_success():
    async def fail(_req):
        raise RateLimited("no", status_code=429, provider="a")

    async def ok(_req):
        return ProviderResponse(text='{"ok":true}', usage=Usage(total_tokens=1), status_code=200)

    client = AsyncClient(
        _config(("a", "b")),
        adapters={"a": FakeAsyncAdapter("a", fail), "b": FakeAsyncAdapter("b", ok)},
    )
    result = await client.acomplete(prompt="hi", response_format="json")
    assert result.provider == "b"
    assert len(result.attempts) == 2
    assert result.attempts[0].ok is False and result.attempts[1].ok is True


async def test_auth_stops_chain():
    async def auth(_req):
        raise ProviderError("auth", status_code=401, provider="a")

    async def ok(_req):
        return ProviderResponse(text="y", usage=Usage(), status_code=200)

    client = AsyncClient(
        _config(("a", "b")),
        adapters={"a": FakeAsyncAdapter("a", auth), "b": FakeAsyncAdapter("b", ok)},
    )
    with pytest.raises(ProviderError):
        await client.acomplete(prompt="hi")


async def test_auth_continue_falls_through():
    async def auth(_req):
        raise ProviderError("auth", status_code=401, provider="a")

    async def ok(_req):
        return ProviderResponse(text="y", usage=Usage(), status_code=200)

    client = AsyncClient(
        _config(("a", "b")),
        adapters={"a": FakeAsyncAdapter("a", auth), "b": FakeAsyncAdapter("b", ok)},
    )
    result = await client.acomplete(prompt="hi", on_auth_failure="continue")
    assert result.provider == "b"
    assert result.attempts[0].ok is False
    assert result.attempts[0].status_code == 401
    assert result.attempts[1].ok is True


async def test_all_providers_cooling_raises_no_eligible():
    cooldowns = CooldownTracker()
    for name in ("a", "b"):
        cooldowns.set_cooldown(name, seconds=60.0)
    client = AsyncClient(_config(("a", "b")), cooldowns=cooldowns, adapters={})
    with pytest.raises(NoEligibleProviders):
        await client.acomplete(prompt="hi")


async def test_all_providers_failed():
    async def fail(_req):
        raise RateLimited("no", status_code=429)

    client = AsyncClient(
        _config(("a", "b")),
        adapters={"a": FakeAsyncAdapter("a", fail), "b": FakeAsyncAdapter("b", fail)},
    )
    with pytest.raises(AllProvidersFailed) as ei:
        await client.acomplete(prompt="hi")
    assert len(ei.value.attempts) == 2


async def test_concurrent_acomplete_respects_max_inflight():
    limiter = InMemoryLimiter(per_provider={"a": ProviderLimit(max_inflight=1)})
    holding = asyncio.Event()
    release = asyncio.Event()
    adapter_calls = 0

    async def gated(_req):
        nonlocal adapter_calls
        adapter_calls += 1
        holding.set()
        await release.wait()
        return ProviderResponse(text="ok", usage=Usage(), status_code=200)

    client = AsyncClient(
        _config(("a",)),
        limiter=limiter,
        adapters={"a": FakeAsyncAdapter("a", gated)},
    )

    async def release_after_peer_denied():
        await holding.wait()
        await asyncio.sleep(0.01)
        release.set()

    release_task = asyncio.create_task(release_after_peer_denied())
    results = await asyncio.gather(
        client.acomplete(prompt="one"),
        client.acomplete(prompt="two"),
        return_exceptions=True,
    )
    await release_task

    successes = [r for r in results if isinstance(r, CompletionResult)]
    failures = [r for r in results if isinstance(r, AllProvidersFailed)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert adapter_calls == 1
    assert failures[0].attempts[0].error_type == "budget"


async def test_cancel_in_flight_acomplete_releases_reservation():
    limiter = InMemoryLimiter(per_provider={"a": ProviderLimit(max_inflight=1)})
    started = asyncio.Event()

    async def hang(_req):
        started.set()
        await asyncio.sleep(3600)
        return ProviderResponse(text="ok", usage=Usage(), status_code=200)

    client = AsyncClient(
        _config(("a",)),
        limiter=limiter,
        adapters={"a": FakeAsyncAdapter("a", hang)},
    )
    task = asyncio.create_task(client.acomplete(prompt="one"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    reservation = limiter.try_reserve("a")
    limiter.release(reservation)


def test_async_client_exported():
    from multiprovider_llm import AsyncClient as Exported

    assert Exported is AsyncClient
