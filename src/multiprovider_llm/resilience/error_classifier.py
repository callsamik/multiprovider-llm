from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from ..errors import ProviderError, RateLimited, ValidationError

_UNAVAILABLE = frozenset({502, 503, 504, 529})
_AUTH = frozenset({401, 403})


@dataclass(frozen=True)
class FallbackDecision:
    should_fallback: bool
    lock_model: bool
    cooldown_s: float | None
    reason: str


def classify_error(
    exc: BaseException,
    *,
    on_auth_failure: Literal["stop", "continue"] = "stop",
) -> FallbackDecision:
    if isinstance(exc, ValidationError):
        return FallbackDecision(True, False, None, "json_validation")
    if isinstance(exc, httpx.TimeoutException):
        return FallbackDecision(True, False, 1.0, "timeout")
    if isinstance(exc, httpx.ConnectError):
        return FallbackDecision(True, False, 1.0, "connect")
    if isinstance(exc, ProviderError):
        body = (exc.body or "").lower()
        if "insufficient_quota" in body or "credits_exhausted" in body:
            return FallbackDecision(True, True, 60.0, "quota_exhausted")
        if "model_not_found" in body or "model_not_supported" in body:
            return FallbackDecision(True, True, None, "model_unavailable")
        status = exc.status_code
        if status == 429 or isinstance(exc, RateLimited):
            return FallbackDecision(True, True, _retry_after_seconds(exc), "http_429")
        if status in _UNAVAILABLE:
            return FallbackDecision(True, False, 5.0, "http_unavailable")
        if status == 500:
            return FallbackDecision(True, False, 1.0, "http_500")
        if status in _AUTH:
            return FallbackDecision(on_auth_failure == "continue", False, None, "http_auth")
        if status == 400:
            return FallbackDecision(False, False, None, "http_400")
    return FallbackDecision(False, False, None, "unknown")


def _retry_after_seconds(exc: ProviderError) -> float:
    raw = None
    for key, value in exc.headers.items():
        if key.lower() == "retry-after":
            raw = value
            break
    if isinstance(raw, str) and raw.isdigit():
        return float(int(raw))
    if isinstance(raw, int) and not isinstance(raw, bool):
        return float(raw)
    return 60.0
