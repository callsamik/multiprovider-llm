from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import replace

from .types import RankedTarget


class LkgpStore:
    def __init__(self, *, band: float = 0.10, ttl_s: float | None = 1800.0) -> None:
        self._band = band
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        self._items: dict[str, tuple[str, str, float]] = {}

    def make_key(self, tier: str | None, task_kind: str | None) -> str:
        return f"{tier or '-'}:{task_kind or '-'}"

    def remember(
        self, key: str, provider: str, model: str, *, now: float | None = None
    ) -> None:
        clock = time.monotonic() if now is None else now
        with self._lock:
            self._items[key] = (provider, model, clock)

    def forget(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def get(self, key: str, *, now: float | None = None) -> tuple[str, str] | None:
        clock = time.monotonic() if now is None else now
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            provider, model, remembered_at = item
            if self._ttl_s is not None and clock - remembered_at >= self._ttl_s:
                self._items.pop(key, None)
                return None
            return (provider, model)

    def promote(
        self,
        ranked: Sequence[RankedTarget],
        key: str,
        *,
        now: float | None = None,
    ) -> tuple[tuple[RankedTarget, ...], bool]:
        remembered = self.get(key, now=now)
        if remembered is None or not ranked:
            return (tuple(ranked), False)
        provider, model = remembered
        best = ranked[0].score
        match_index = None
        for index, target in enumerate(ranked):
            if target.provider == provider and target.model == model:
                match_index = index
                break
        if match_index is None:
            return (tuple(ranked), False)
        chosen = ranked[match_index]
        if chosen.score < best * (1.0 - self._band):
            return (tuple(ranked), False)
        reordered = [chosen, *[t for i, t in enumerate(ranked) if i != match_index]]
        numbered = tuple(replace(target, rank=i) for i, target in enumerate(reordered, start=1))
        return (numbered, True)
