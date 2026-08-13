"""Sync Client.complete orchestration.

``CompletionResult.latency_ms`` is total wall-clock orchestration time
(routing + all provider attempts), not a single HTTP round-trip.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NoReturn

from .config import LibraryConfig
from .errors import (
    AllProvidersFailed,
    BudgetExceeded,
    ConfigError,
    NoEligibleProviders,
    RateLimited,
    ValidationError,
)
from .limits import CooldownTracker, InMemoryLimiter, ProviderLimit
from .protocols import Limiter, ProviderAdapter, Reservation
from .providers.registry import get_provider
from .routing import is_retryable, resolve_chain, resolve_model
from .serialization import extract_json_text, normalize_messages
from .types import (
    AttemptRecord,
    CompletionResult,
    Message,
    ProviderRequest,
    ProviderResponse,
)

_DEFAULT_MAX_INFLIGHT = 32
_DEFAULT_COOLDOWN_S = 1.0
_MESSAGE_LIMIT = 500


def _default_limiter(config: LibraryConfig) -> InMemoryLimiter:
    per_provider: dict[str, ProviderLimit] = {}
    for name, pcfg in config.providers.items():
        if pcfg.rate_limits is not None:
            per_provider[name] = pcfg.rate_limits
        else:
            per_provider[name] = ProviderLimit(max_inflight=_DEFAULT_MAX_INFLIGHT)
    return InMemoryLimiter(per_provider=per_provider, global_budget=config.global_budget)


def _truncate(message: str | None) -> str | None:
    if message is None:
        return None
    if len(message) <= _MESSAGE_LIMIT:
        return message
    return message[:_MESSAGE_LIMIT]


def _retry_after_seconds(exc: RateLimited) -> float:
    raw = None
    for key, value in (exc.headers or {}).items():
        if str(key).lower() == "retry-after":
            raw = value
            break
    if raw is None:
        return _DEFAULT_COOLDOWN_S
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_COOLDOWN_S
    return seconds if seconds > 0 else _DEFAULT_COOLDOWN_S


@dataclass(frozen=True)
class _PreparedCall:
    started: float
    normalized: tuple[Message, ...]
    chain: tuple[str, ...]
    tier: str | None
    response_format: Literal["text", "json"]
    json_schema: Mapping[str, Any] | None
    timeout_s: float | None
    include_raw: bool


def _prepare_call(
    config: LibraryConfig,
    *,
    prompt: str | None,
    messages: Sequence[Message | Mapping[str, Any]] | None,
    tier: str | None,
    provider_chain: Sequence[str] | None,
    response_format: Literal["text", "json"],
    json_schema: Mapping[str, Any] | None,
    freshness_required: bool,
    timeout_s: float | None,
    include_raw: bool,
) -> _PreparedCall:
    started = time.perf_counter()
    if json_schema is not None and response_format != "json":
        raise ValidationError("json_schema requires response_format='json'")

    normalized = tuple(normalize_messages(prompt=prompt, messages=messages))
    chain = resolve_chain(
        config,
        tier=tier,
        provider_chain=tuple(provider_chain) if provider_chain is not None else None,
        freshness_required=freshness_required,
    )
    if not chain:
        raise NoEligibleProviders("no eligible providers after routing filters")
    return _PreparedCall(
        started=started,
        normalized=normalized,
        chain=chain,
        tier=tier,
        response_format=response_format,
        json_schema=json_schema,
        timeout_s=timeout_s,
        include_raw=include_raw,
    )


def _try_reserve_attempt(
    limiter: Limiter,
    cooldowns: CooldownTracker,
    name: str,
    attempts: list[AttemptRecord],
) -> Reservation | None:
    if cooldowns.is_cooling(name):
        return None
    try:
        return limiter.try_reserve(name)
    except RateLimited as exc:
        attempts.append(
            AttemptRecord(
                provider=name,
                model=None,
                ok=False,
                error_type="budget",
                status_code=None,
                latency_ms=0.0,
                message=_truncate(str(exc)),
            )
        )
        return None
    except BudgetExceeded:
        raise


def _build_request(
    config: LibraryConfig,
    name: str,
    prepared: _PreparedCall,
) -> tuple[str, ProviderRequest]:
    model = resolve_model(config, name, prepared.tier)
    request = ProviderRequest(
        messages=prepared.normalized,
        model=model,
        timeout_s=prepared.timeout_s,
        response_format=prepared.response_format,
        json_schema=prepared.json_schema,
        include_raw=prepared.include_raw,
    )
    return model, request


def _handle_adapter_exception(
    limiter: Limiter,
    cooldowns: CooldownTracker,
    reservation: Reservation,
    name: str,
    model: str,
    exc: Exception,
    call_started: float,
    attempts: list[AttemptRecord],
) -> None:
    limiter.release(reservation)
    latency_ms = (time.perf_counter() - call_started) * 1000
    if isinstance(exc, ValidationError) or not is_retryable(exc):
        raise
    attempts.append(
        AttemptRecord(
            provider=name,
            model=model,
            ok=False,
            error_type=type(exc).__name__,
            status_code=getattr(exc, "status_code", None),
            latency_ms=latency_ms,
            message=_truncate(str(exc)),
        )
    )
    if isinstance(exc, RateLimited):
        cooldowns.set_cooldown(name, seconds=_retry_after_seconds(exc))


def _handle_success(
    limiter: Limiter,
    reservation: Reservation,
    name: str,
    model: str,
    response: ProviderResponse,
    prepared: _PreparedCall,
    attempts: list[AttemptRecord],
    latency_ms: float,
) -> CompletionResult | None:
    text = response.text
    if prepared.response_format == "json":
        try:
            text = extract_json_text(response.text)
        except ValidationError as exc:
            limiter.release(reservation)
            attempts.append(
                AttemptRecord(
                    provider=name,
                    model=model,
                    ok=False,
                    error_type="ValidationError",
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                    message=_truncate(str(exc)),
                )
            )
            return None

    limiter.finalize(reservation, usage=response.usage)
    attempts.append(
        AttemptRecord(
            provider=name,
            model=model,
            ok=True,
            error_type=None,
            status_code=response.status_code,
            latency_ms=latency_ms,
            message=None,
        )
    )
    return CompletionResult(
        text=text,
        provider=name,
        model=model,
        tier=prepared.tier,
        latency_ms=(time.perf_counter() - prepared.started) * 1000,
        usage=response.usage,
        attempts=tuple(attempts),
        raw=response.raw if prepared.include_raw else None,
    )


def _raise_if_exhausted(attempts: list[AttemptRecord]) -> NoReturn:
    if not attempts:
        raise NoEligibleProviders("no eligible providers after routing filters")
    raise AllProvidersFailed("all providers failed", attempts=tuple(attempts))


class _ClientCore:
    def __init__(
        self,
        config: LibraryConfig,
        *,
        limiter: Limiter | None = None,
        cooldowns: CooldownTracker | None = None,
        adapters: Mapping[str, ProviderAdapter] | None = None,
    ) -> None:
        self._config = config
        self._limiter = limiter if limiter is not None else _default_limiter(config)
        self._cooldowns = cooldowns if cooldowns is not None else CooldownTracker()
        self._adapters = dict(adapters) if adapters is not None else None
        self._resolved: dict[str, ProviderAdapter] = {}

    def _adapter_for(self, name: str) -> ProviderAdapter:
        if self._adapters is not None:
            adapter = self._adapters.get(name)
            if adapter is None:
                raise ConfigError(f"no adapter registered for provider {name!r}")
            return adapter
        found = self._resolved.get(name)
        if found is None:
            found = get_provider(name)
            self._resolved[name] = found
        return found


class Client(_ClientCore):
    def complete(
        self,
        *,
        prompt: str | None = None,
        messages: Sequence[Message | Mapping[str, Any]] | None = None,
        tier: str | None = None,
        provider_chain: Sequence[str] | None = None,
        response_format: Literal["text", "json"] = "text",
        json_schema: Mapping[str, Any] | None = None,
        freshness_required: bool = False,
        timeout_s: float | None = None,
        include_raw: bool = False,
    ) -> CompletionResult:
        prepared = _prepare_call(
            self._config,
            prompt=prompt,
            messages=messages,
            tier=tier,
            provider_chain=provider_chain,
            response_format=response_format,
            json_schema=json_schema,
            freshness_required=freshness_required,
            timeout_s=timeout_s,
            include_raw=include_raw,
        )
        attempts: list[AttemptRecord] = []
        for name in prepared.chain:
            reservation = _try_reserve_attempt(
                self._limiter, self._cooldowns, name, attempts
            )
            if reservation is None:
                continue
            model, request = _build_request(self._config, name, prepared)
            call_started = time.perf_counter()
            try:
                adapter = self._adapter_for(name)
                response = adapter.complete(request)
            except Exception as exc:
                _handle_adapter_exception(
                    self._limiter,
                    self._cooldowns,
                    reservation,
                    name,
                    model,
                    exc,
                    call_started,
                    attempts,
                )
                continue
            latency_ms = (time.perf_counter() - call_started) * 1000
            result = _handle_success(
                self._limiter,
                reservation,
                name,
                model,
                response,
                prepared,
                attempts,
                latency_ms,
            )
            if result is not None:
                return result
        _raise_if_exhausted(attempts)
