import httpx
import pytest

from multiprovider_llm.errors import ProviderError, RateLimited, ValidationError
from multiprovider_llm.resilience.error_classifier import classify_error


@pytest.mark.parametrize(
    "exc, on_auth, should_fallback, lock_model, cooldown_s, reason",
    [
        (RateLimited("hot", status_code=429, headers={"Retry-After": "12"}), "stop", True, True, 12.0, "http_429"),
        (ProviderError("x", status_code=429), "stop", True, True, 60.0, "http_429"),
        (ProviderError("x", status_code=503), "stop", True, False, 5.0, "http_unavailable"),
        (ProviderError("x", status_code=502), "stop", True, False, 5.0, "http_unavailable"),
        (ProviderError("x", status_code=504), "stop", True, False, 5.0, "http_unavailable"),
        (ProviderError("x", status_code=529), "stop", True, False, 5.0, "http_unavailable"),
        (ProviderError("x", status_code=500), "stop", True, False, 1.0, "http_500"),
        (ProviderError("x", status_code=401), "stop", False, False, None, "http_auth"),
        (ProviderError("x", status_code=403), "continue", True, False, None, "http_auth"),
        (httpx.TimeoutException("t"), "stop", True, False, 1.0, "timeout"),
        (httpx.ConnectError("c"), "stop", True, False, 1.0, "connect"),
        (ProviderError("insufficient_quota", status_code=400, body="insufficient_quota"), "stop", True, True, 60.0, "quota_exhausted"),
        (ProviderError("credits_exhausted", body="credits_exhausted"), "stop", True, True, 60.0, "quota_exhausted"),
        (ProviderError("missing", status_code=404, body="model_not_found"), "stop", True, True, None, "model_unavailable"),
        (ProviderError("nope", status_code=400, body="model_not_supported"), "stop", True, True, None, "model_unavailable"),
        (ValidationError("json"), "stop", True, False, None, "json_validation"),
        (ProviderError("bad prompt", status_code=400, body="invalid request"), "stop", False, False, None, "http_400"),
        (RuntimeError("boom"), "stop", False, False, None, "unknown"),
    ],
)
def test_classify_error_table(exc, on_auth, should_fallback, lock_model, cooldown_s, reason):
    decision = classify_error(exc, on_auth_failure=on_auth)
    assert decision.should_fallback is should_fallback
    assert decision.lock_model is lock_model
    assert decision.cooldown_s == cooldown_s
    assert decision.reason == reason
