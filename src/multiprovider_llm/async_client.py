"""Async AsyncClient.acomplete orchestration.

``CompletionResult.latency_ms`` is total wall-clock orchestration time
(routing + all provider attempts), not a single HTTP round-trip.

Uses native ``await adapter.acomplete`` — never ``asyncio.to_thread``.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from .client import (
    _build_request,
    _ClientCore,
    _handle_adapter_exception,
    _handle_success,
    _notify_failure,
    _prepare_call,
    _safe_hook,
    _try_reserve_attempt,
)
from .errors import AllProvidersFailed, NoEligibleProviders
from .types import AttemptRecord, CompletionResult, Message


class AsyncClient(_ClientCore):
    async def acomplete(
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
        max_tokens: int | None = None,
        on_auth_failure: Literal["stop", "continue"] = "stop",
    ) -> CompletionResult:
        try:
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
                max_tokens=max_tokens,
            )
        except BaseException as exc:
            _notify_failure(self._hooks, exc, ())
            raise
        attempts: list[AttemptRecord] = []
        for name in prepared.chain:
            reservation = _try_reserve_attempt(
                self._limiter, self._cooldowns, name, attempts, self._hooks
            )
            if reservation is None:
                continue
            model, request = _build_request(self._config, name, prepared)
            call_started = time.perf_counter()
            finalized = False
            try:
                try:
                    adapter = self._adapter_for(name)
                    response = await adapter.acomplete(request)
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
                        on_auth_failure=on_auth_failure,
                        hooks=self._hooks,
                    )
                    finalized = True
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
                    self._hooks,
                )
                finalized = True
                if result is not None:
                    if self._hooks is not None:
                        _safe_hook(self._hooks.on_success, result)
                    return result
            finally:
                if not finalized:
                    self._limiter.release(reservation)
        if not attempts:
            error: BaseException = NoEligibleProviders(
                "no eligible providers after routing filters"
            )
        else:
            error = AllProvidersFailed("all providers failed", attempts=tuple(attempts))
        _notify_failure(self._hooks, error, tuple(attempts))
        raise error
