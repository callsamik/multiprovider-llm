from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Candidate:
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
