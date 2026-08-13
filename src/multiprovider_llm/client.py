"""Sync Client.complete orchestration.

``CompletionResult.latency_ms`` is total wall-clock orchestration time
(routing + all provider attempts), not a single HTTP round-trip.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal

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
from .protocols import Limiter, ProviderAdapter
from .providers.registry import get_provider
from .routing import is_retryable, resolve_chain, resolve_model
from .serialization import extract_json_text, normalize_messages
from .types import AttemptRecord, CompletionResult, Message, ProviderRequest

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


class Client:
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
        started = time.perf_counter()
        if json_schema is not None and response_format != "json":
            raise ValidationError("json_schema requires response_format='json'")

        normalized = tuple(normalize_messages(prompt=prompt, messages=messages))
        chain = resolve_chain(
            self._config,
            tier=tier,
            provider_chain=tuple(provider_chain) if provider_chain is not None else None,
            freshness_required=freshness_required,
        )
        if not chain:
            raise NoEligibleProviders("no eligible providers after routing filters")

        attempts: list[AttemptRecord] = []
        for name in chain:
            if self._cooldowns.is_cooling(name):
                continue
            try:
                reservation = self._limiter.try_reserve(name)
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
                continue
            except BudgetExceeded:
                raise

            model = resolve_model(self._config, name, tier)
            request = ProviderRequest(
                messages=normalized,
                model=model,
                timeout_s=timeout_s,
                response_format=response_format,
                json_schema=json_schema,
                include_raw=include_raw,
            )
            call_started = time.perf_counter()
            try:
                adapter = self._adapter_for(name)
                response = adapter.complete(request)
            except Exception as exc:
                self._limiter.release(reservation)
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
                    self._cooldowns.set_cooldown(name, seconds=_retry_after_seconds(exc))
                continue

            latency_ms = (time.perf_counter() - call_started) * 1000
            text = response.text
            if response_format == "json":
                try:
                    text = extract_json_text(response.text)
                except ValidationError as exc:
                    self._limiter.release(reservation)
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
                    continue

            self._limiter.finalize(reservation, usage=response.usage)
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
                tier=tier,
                latency_ms=(time.perf_counter() - started) * 1000,
                usage=response.usage,
                attempts=tuple(attempts),
                raw=response.raw if include_raw else None,
            )

        raise AllProvidersFailed("all providers failed", attempts=tuple(attempts))

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
