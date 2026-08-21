from __future__ import annotations

from collections.abc import Sequence

from ..protocols import HealthMetricsReader, QuotaReader
from .types import FACTOR_NAMES, Candidate, ScoringFactors, ScoringWeights

DEFAULT_WEIGHTS = ScoringWeights()


def clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def cost_inv_for(candidate: Candidate) -> float:
    return 1.0 if candidate.cost_tier == "free" else 0.0


def tier_fit_for(candidate: Candidate, tier: str | None) -> float:
    if tier is None:
        return 1.0
    return float(candidate.tier_affinity.get(tier, 0.0))


def quota_factor(reader: QuotaReader | None, candidate: Candidate) -> float:
    if reader is None:
        return 1.0
    remaining = reader.quota_remaining_pct(candidate.provider, candidate.model)
    if remaining is None:
        return 1.0
    return clamp01(remaining)


def health_factors(
    reader: HealthMetricsReader | None, candidate: Candidate
) -> tuple[float, float]:
    if reader is None:
        return (1.0, 1.0)
    error_rate = reader.error_rate(candidate.provider, candidate.model)
    health = 1.0 if error_rate is None else clamp01(1.0 - error_rate)
    p95 = reader.p95_latency_ms(candidate.provider, candidate.model)
    latency_inv = 1.0 if p95 is None else 1.0 / (1.0 + p95 / 1000.0)
    return (health, latency_inv)


def factors_for(
    candidate: Candidate,
    *,
    tier: str | None,
    quota_reader: QuotaReader | None,
    health_reader: HealthMetricsReader | None,
) -> ScoringFactors:
    health, latency_inv = health_factors(health_reader, candidate)
    return ScoringFactors(
        quota=quota_factor(quota_reader, candidate),
        health=health,
        latency_inv=latency_inv,
        tier_fit=tier_fit_for(candidate, tier),
        cost_inv=cost_inv_for(candidate),
    )


def constant_factors_across(rows: Sequence[ScoringFactors]) -> frozenset[str]:
    if not rows:
        return frozenset()
    constant: set[str] = set()
    for name in FACTOR_NAMES:
        values = {getattr(row, name) for row in rows}
        if len(values) == 1:
            constant.add(name)
    return frozenset(constant)


def calculate_score(
    factors: ScoringFactors,
    weights: ScoringWeights,
    *,
    constant_factors: frozenset[str] = frozenset(),
) -> float:
    active = {k: w for k, w in weights.as_dict().items() if k not in constant_factors}
    total = sum(active.values())
    if total == 0.0:
        return 0.0
    return clamp01(sum((w / total) * float(getattr(factors, k)) for k, w in active.items()))
