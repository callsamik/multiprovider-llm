from multiprovider_llm.errors import (
    AllProvidersFailed,
    NoEligibleProviders,
    ProviderError,
    ValidationError,
)
from multiprovider_llm.types import (
    AttemptRecord,
    CompletionResult,
    Message,
    ProviderRequest,
    ProviderResponse,
    Usage,
)


def test_no_eligible_distinct_from_all_failed():
    assert NoEligibleProviders is not AllProvidersFailed
    assert issubclass(NoEligibleProviders, Exception)
    assert issubclass(AllProvidersFailed, Exception)


def test_provider_error_truncation_fields():
    err = ProviderError("boom", status_code=500, body="x" * 5000, headers={"a": "1"})
    assert err.status_code == 500
    assert len(err.body) <= 500
    assert err.headers == {"a": "1"}


def test_usage_extras_and_completion_result_defaults():
    usage = Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3, extras={"cache": 9})
    result = CompletionResult(
        text="{}",
        provider="openai",
        model="gpt-4.1-mini",
        tier="simple",
        latency_ms=12.5,
        usage=usage,
        attempts=(AttemptRecord(
            provider="openai",
            model="gpt-4.1-mini",
            ok=True,
            error_type=None,
            status_code=200,
            latency_ms=12.5,
            message=None,
        ),),
        raw=None,
    )
    assert result.raw is None
    assert result.usage.extras["cache"] == 9


def test_provider_request_uses_timeout_s():
    req = ProviderRequest(
        messages=(Message(role="user", content="hi"),),
        model="m",
        timeout_s=5.0,
        response_format="text",
        json_schema=None,
        include_raw=False,
        extras={},
    )
    assert req.timeout_s == 5.0
    assert not hasattr(req, "timeout") or not callable(getattr(req, "timeout", None))
