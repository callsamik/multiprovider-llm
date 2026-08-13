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
    _prepare_call,
    _raise_if_exhausted,
    _try_reserve_attempt,
)
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
