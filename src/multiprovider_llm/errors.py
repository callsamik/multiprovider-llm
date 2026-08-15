from __future__ import annotations

from typing import Any, Mapping, Sequence


class MultiproviderError(Exception):
    """Base error for multiprovider-llm.

    ``attempts`` holds any ``AttemptRecord``s already made when the error is raised
    (empty for pre-call validation / config failures with no HTTP attempt).
    """

    attempts: tuple[Any, ...] = ()


class ValidationError(MultiproviderError):
    pass


class ConfigError(MultiproviderError):
    pass


class ProviderError(MultiproviderError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        headers: Mapping[str, Any] | None = None,
        body: str = "",
        provider: str | None = None,
        attempts: Sequence[Any] = (),
    ) -> None:
        truncated = body if len(body) <= 500 else body[:500]
        super().__init__(message)
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.body = truncated
        self.provider = provider
        self.attempts = tuple(attempts)


class RateLimited(ProviderError):
    pass


class BudgetExceeded(MultiproviderError):
    """Global inflight budget exhausted."""


class NoEligibleProviders(MultiproviderError):
    """Chain empty after filters — no HTTP attempts were made."""


class AllProvidersFailed(MultiproviderError):
    """At least one provider was attempted; all failed."""

    def __init__(self, message: str, *, attempts: Sequence[Any] = ()) -> None:
        super().__init__(message)
        self.attempts = tuple(attempts)
