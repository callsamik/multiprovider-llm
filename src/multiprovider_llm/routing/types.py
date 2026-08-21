from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Candidate:
    """Executable target identity for ranking and (later) dispatch.

    Does not carry ``pool_key``. Shared-quota identity lives in catalog
    data and is interpreted by ``QuotaReader``.
    """

    provider: str
    model: str
    adapter: Literal["gemini", "anthropic", "openai_compat"]
    base_url: str
    cost_tier: Literal["free", "paid"]
    freshness_ok: bool
    tier_affinity: Mapping[str, float]
    http_referer: str | None


@dataclass(frozen=True)
class FilterNote:
    provider: str
    model: str
    reason: str


@dataclass(frozen=True)
class PrefilterResult:
    eligible: tuple[Candidate, ...]
    notes: tuple[FilterNote, ...]


FACTOR_NAMES = ("quota", "health", "latency_inv", "tier_fit", "cost_inv")


@dataclass(frozen=True)
class ScoringWeights:
    quota: float = 0.30
    health: float = 0.25
    latency_inv: float = 0.20
    tier_fit: float = 0.15
    cost_inv: float = 0.10

    def as_dict(self) -> dict[str, float]:
        return {
            "quota": self.quota,
            "health": self.health,
            "latency_inv": self.latency_inv,
            "tier_fit": self.tier_fit,
            "cost_inv": self.cost_inv,
        }


@dataclass(frozen=True)
class ScoringFactors:
    quota: float
    health: float
    latency_inv: float
    tier_fit: float
    cost_inv: float


@dataclass(frozen=True)
class RankedTarget:
    """Ranking decision for one executable target.

    Join back to a ``Candidate`` with ``(provider, model)`` for dispatch
    (adapter, ``base_url``, ``http_referer``). This type does not carry
    execution configuration.

    ``score`` is comparative ranking information among the eligible set,
    not an absolute quality rating. A lone eligible candidate may score
    ``0.0`` after constant factors are dropped; that does not mean the
    provider is unhealthy.
    """

    provider: str
    model: str
    score: float
    factors: ScoringFactors
    rank: int


@dataclass(frozen=True)
class RoutingDiagnostics:
    pool_size: int
    filtered_size: int
    ranked_targets: tuple[RankedTarget, ...]
    lkgp_promoted: bool
    filter_notes: tuple[FilterNote, ...]


@dataclass(frozen=True)
class RankingResult:
    """Output of ``rank_candidates`` — the M4 input boundary.

    ``ranked_targets`` are ranking decisions. Execution still requires the
    originating ``Candidate`` pool. ``diagnostics.ranked_targets`` is the
    same ordered list (post-LKGP).
    """

    ranked_targets: tuple[RankedTarget, ...]
    diagnostics: RoutingDiagnostics
