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
