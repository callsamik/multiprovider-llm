from __future__ import annotations

from collections.abc import Sequence

from ..protocols import CooldownReader, QuotaReader
from ..resilience.model_lockout import ModelLockoutTracker
from .types import Candidate, FilterNote, PrefilterResult


def prefilter_candidates(
    candidates: Sequence[Candidate],
    *,
    lockout: ModelLockoutTracker,
    quota_reader: QuotaReader | None = None,
    cooldown_reader: CooldownReader | None = None,
    known_adapters: frozenset[str] | None = None,
    min_quota_pct: float = 0.05,
    now: float | None = None,
) -> PrefilterResult:
    eligible: list[Candidate] = []
    notes: list[FilterNote] = []
    for candidate in candidates:
        reason: str | None = None
        if lockout.is_locked(candidate.provider, candidate.model, now=now):
            reason = "lockout"
        elif cooldown_reader is not None and cooldown_reader.is_cooling(candidate.provider):
            reason = "cooldown"
        elif quota_reader is not None:
            remaining = quota_reader.quota_remaining_pct(candidate.provider, candidate.model)
            if remaining is not None and remaining < min_quota_pct:
                reason = "quota_cutoff"
        if reason is None and known_adapters is not None and candidate.adapter not in known_adapters:
            reason = "missing_adapter"
        if reason is not None:
            notes.append(FilterNote(candidate.provider, candidate.model, reason))
            continue
        eligible.append(candidate)
    return PrefilterResult(eligible=tuple(eligible), notes=tuple(notes))
