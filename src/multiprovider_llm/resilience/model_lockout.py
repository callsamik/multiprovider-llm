from __future__ import annotations

import math
import threading
import time


class ModelLockoutTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until: dict[tuple[str, str], float] = {}

    def lock(
        self,
        provider: str,
        model: str,
        cooldown_s: float | None,
        *,
        now: float | None = None,
    ) -> None:
        clock = time.monotonic() if now is None else now
        until = math.inf if cooldown_s is None else clock + cooldown_s
        with self._lock:
            self._until[(provider, model)] = until

    def is_locked(self, provider: str, model: str, *, now: float | None = None) -> bool:
        return self.remaining_seconds(provider, model, now=now) > 0.0

    def remaining_seconds(
        self, provider: str, model: str, *, now: float | None = None
    ) -> float:
        clock = time.monotonic() if now is None else now
        with self._lock:
            until = self._until.get((provider, model))
            if until is None:
                return 0.0
            if until == math.inf:
                return math.inf
            left = until - clock
            if left <= 0.0:
                self._until.pop((provider, model), None)
                return 0.0
            return left
