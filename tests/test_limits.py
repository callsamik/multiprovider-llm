import threading
import time

import pytest

from multiprovider_llm.errors import BudgetExceeded, RateLimited
from multiprovider_llm.limits import CooldownTracker, InMemoryLimiter, ProviderLimit
from multiprovider_llm.types import Usage


def test_reserve_finalize_release():
    lim = InMemoryLimiter(
        per_provider={"openai": ProviderLimit(max_inflight=1)},
        global_budget=2,
    )
    r = lim.try_reserve("openai", tokens=1)
    with pytest.raises(RateLimited):
        lim.try_reserve("openai", tokens=1)
    lim.finalize(r, usage=Usage(total_tokens=1))
    r2 = lim.try_reserve("openai", tokens=1)
    lim.release(r2)


def test_global_budget():
    lim = InMemoryLimiter(
        per_provider={"a": ProviderLimit(max_inflight=10), "b": ProviderLimit(max_inflight=10)},
        global_budget=1,
    )
    r = lim.try_reserve("a")
    with pytest.raises(BudgetExceeded):
        lim.try_reserve("b")
    lim.release(r)


def test_threaded_reserves():
    lim = InMemoryLimiter(per_provider={"x": ProviderLimit(max_inflight=5)}, global_budget=5)
    ok = []
    err = []

    def worker():
        try:
            r = lim.try_reserve("x")
            time.sleep(0.01)
            lim.release(r)
            ok.append(1)
        except Exception as e:  # noqa: BLE001
            err.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) + len(err) == 20
    assert len(ok) >= 5


def test_cooldown():
    cd = CooldownTracker()
    cd.set_cooldown("groq", seconds=0.05)
    assert cd.is_cooling("groq")
    time.sleep(0.06)
    assert not cd.is_cooling("groq")
