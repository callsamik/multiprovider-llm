from __future__ import annotations

import math
import threading
from collections import deque

from ..types import AttemptRecord


class RollingHealthMetrics:
    def __init__(self, window_size: int = 50) -> None:
        self._window_size = window_size
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], deque[AttemptRecord]] = {}

    def record(self, attempt: AttemptRecord) -> None:
        key = (attempt.provider, attempt.model or "")
        with self._lock:
            bucket = self._windows.get(key)
            if bucket is None:
                bucket = deque(maxlen=self._window_size)
                self._windows[key] = bucket
            bucket.append(attempt)

    def error_rate(self, provider: str, model: str) -> float | None:
        with self._lock:
            bucket = self._windows.get((provider, model))
            if not bucket:
                return None
            failures = sum(1 for item in bucket if not item.ok)
            return failures / len(bucket)

    def p95_latency_ms(self, provider: str, model: str) -> float | None:
        with self._lock:
            bucket = self._windows.get((provider, model))
            if not bucket:
                return None
            values = sorted(item.latency_ms for item in bucket)
        index = min(len(values) - 1, max(0, math.ceil(0.95 * len(values)) - 1))
        return values[index]
