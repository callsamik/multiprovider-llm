from multiprovider_llm.routing.metrics import RollingHealthMetrics
from multiprovider_llm.types import AttemptRecord


def _rec(provider="groq", model="m", ok=True, latency_ms=10.0):
    return AttemptRecord(
        provider=provider,
        model=model,
        ok=ok,
        error_type=None if ok else "RateLimited",
        status_code=200 if ok else 429,
        latency_ms=latency_ms,
        message=None,
    )


def test_empty_window_unknown():
    metrics = RollingHealthMetrics()
    assert metrics.error_rate("groq", "m") is None
    assert metrics.p95_latency_ms("groq", "m") is None


def test_error_rate_and_p95():
    metrics = RollingHealthMetrics(window_size=10)
    for i in range(4):
        metrics.record(_rec(ok=True, latency_ms=10.0 + i))
    metrics.record(_rec(ok=False, latency_ms=50.0))
    assert metrics.error_rate("groq", "m") == 0.2
    assert metrics.p95_latency_ms("groq", "m") == 50.0


def test_window_evicts():
    metrics = RollingHealthMetrics(window_size=2)
    metrics.record(_rec(ok=False, latency_ms=1))
    metrics.record(_rec(ok=False, latency_ms=1))
    metrics.record(_rec(ok=True, latency_ms=1))
    metrics.record(_rec(ok=True, latency_ms=1))
    assert metrics.error_rate("groq", "m") == 0.0
