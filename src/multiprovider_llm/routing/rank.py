from __future__ import annotations

from collections.abc import Sequence

from ..protocols import CooldownReader, HealthMetricsReader, QuotaReader
from ..resilience.model_lockout import ModelLockoutTracker
from .lkgp import LkgpStore
from .prefilter import prefilter_candidates
from .scoring import DEFAULT_WEIGHTS, calculate_score, constant_factors_across, factors_for
from .types import (
    Candidate,
    RankedTarget,
    RankingResult,
    RoutingDiagnostics,
    ScoringWeights,
)


def rank_candidates(
    candidates: Sequence[Candidate],
    *,
    tier: str | None,
    task_kind: str | None,
    lockout: ModelLockoutTracker,
    lkgp: LkgpStore,
    quota_reader: QuotaReader | None = None,
    cooldown_reader: CooldownReader | None = None,
    health_reader: HealthMetricsReader | None = None,
    known_adapters: frozenset[str] | None = None,
    weights: ScoringWeights | None = None,
    min_quota_pct: float = 0.05,
    now: float | None = None,
) -> RankingResult:
    used_weights = weights if weights is not None else DEFAULT_WEIGHTS
    pool_size = len(candidates)
    filtered = prefilter_candidates(
        candidates,
        lockout=lockout,
        quota_reader=quota_reader,
        cooldown_reader=cooldown_reader,
        known_adapters=known_adapters,
        min_quota_pct=min_quota_pct,
        now=now,
    )
    factor_rows = [
        factors_for(
            candidate,
            tier=tier,
            quota_reader=quota_reader,
            health_reader=health_reader,
        )
        for candidate in filtered.eligible
    ]
    constant = constant_factors_across(factor_rows)
    scored: list[RankedTarget] = []
    for candidate, factors in zip(filtered.eligible, factor_rows, strict=True):
        score = calculate_score(factors, used_weights, constant_factors=constant)
        scored.append(
            RankedTarget(
                provider=candidate.provider,
                model=candidate.model,
                score=score,
                factors=factors,
                rank=0,
            )
        )
    scored.sort(key=lambda target: (-target.score, target.provider, target.model))
    ranked = tuple(
        RankedTarget(
            provider=target.provider,
            model=target.model,
            score=target.score,
            factors=target.factors,
            rank=index,
        )
        for index, target in enumerate(scored, start=1)
    )
    ranked, promoted = lkgp.promote(
        ranked, lkgp.make_key(tier, task_kind), now=now
    )
    diagnostics = RoutingDiagnostics(
        pool_size=pool_size,
        filtered_size=len(filtered.eligible),
        ranked_targets=ranked,
        lkgp_promoted=promoted,
        filter_notes=filtered.notes,
    )
    return RankingResult(ranked_targets=ranked, diagnostics=diagnostics)
