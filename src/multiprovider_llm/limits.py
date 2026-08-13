from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Mapping

from .errors import BudgetExceeded, RateLimited
from .protocols import Reservation
from .types import Usage


@dataclass(frozen=True)
class ProviderLimit:
    max_inflight: int
    max_tokens_per_minute: int | None = None


@dataclass(frozen=True)
class MemoryReservation:
    provider: str
    token_estimate: int | None


class InMemoryLimiter:
    def __init__(
        self,
        per_provider: Mapping[str, ProviderLimit],
        global_budget: int | None = None,
    ) -> None:
        self._per_provider = dict(per_provider)
        self._global_budget = global_budget
        self._lock = threading.Lock()
        self._inflight: dict[str, int] = {}
        self._global_inflight = 0
        self._held: set[int] = set()

    def _limit_for(self, provider: str) -> ProviderLimit:
        found = self._per_provider.get(provider)
        if found is None:
            return ProviderLimit(max_inflight=1)
        return found

    def try_reserve(self, provider: str, *, tokens: int | None = None) -> MemoryReservation:
        with self._lock:
            limit = self._limit_for(provider)
            current = self._inflight.get(provider, 0)
            if current >= limit.max_inflight:
                raise RateLimited(
                    f"{provider} inflight limit exceeded",
                    status_code=None,
                    provider=provider,
                )
            if self._global_budget is not None and self._global_inflight >= self._global_budget:
                raise BudgetExceeded("global inflight budget exceeded")
            self._inflight[provider] = current + 1
            self._global_inflight += 1
            reservation = MemoryReservation(provider=provider, token_estimate=tokens)
            self._held.add(id(reservation))
            return reservation

    def finalize(self, reservation: Reservation, *, usage: Usage) -> None:
        del usage  # v1: release semantics only
        self._drop(reservation)

    def release(self, reservation: Reservation) -> None:
        self._drop(reservation)

    def _drop(self, reservation: Reservation) -> None:
        with self._lock:
            key = id(reservation)
            if key not in self._held:
                return
            self._held.discard(key)
            provider = reservation.provider
            current = self._inflight.get(provider, 0)
            if current > 0:
                self._inflight[provider] = current - 1
            if self._global_inflight > 0:
                self._global_inflight -= 1


class CooldownTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until: dict[str, float] = {}

    def set_cooldown(self, provider: str, *, seconds: float) -> None:
        with self._lock:
            self._until[provider] = time.monotonic() + seconds

    def is_cooling(self, provider: str) -> bool:
        with self._lock:
            until = self._until.get(provider)
            if until is None:
                return False
            return time.monotonic() < until
