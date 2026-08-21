import inspect

from multiprovider_llm.routing.scoring import (
    calculate_score,
    constant_factors_across,
    cost_inv_for,
    factors_for,
    tier_fit_for,
)
from multiprovider_llm.routing.types import Candidate, ScoringFactors, ScoringWeights


def _cand(provider="a", model="m", cost_tier="free", affinity=None):
    return Candidate(
        provider=provider,
        model=model,
        adapter="openai_compat",
        base_url="https://example.test",
        cost_tier=cost_tier,
        freshness_ok=True,
        tier_affinity=affinity or {"standard": 0.5, "complex": 1.0},
        http_referer=None,
    )


def test_tier_fit_catalog_only():
    c = _cand(affinity={"standard": 0.2, "complex": 0.9})
    assert tier_fit_for(c, "complex") == 0.9
    assert tier_fit_for(c, "standard") == 0.2
    assert tier_fit_for(c, "simple") == 0.0
    assert tier_fit_for(c, None) == 1.0


def test_cost_inv_free_vs_paid():
    assert cost_inv_for(_cand(cost_tier="free")) == 1.0
    assert cost_inv_for(_cand(cost_tier="paid")) == 0.0


def test_constant_cost_inv_dropped_under_all_free():
    rows = (
        ScoringFactors(quota=0.2, health=1.0, latency_inv=1.0, tier_fit=0.5, cost_inv=1.0),
        ScoringFactors(quota=0.8, health=1.0, latency_inv=1.0, tier_fit=0.5, cost_inv=1.0),
    )
    constant = constant_factors_across(rows)
    assert "cost_inv" in constant
    assert "quota" not in constant
    weights = ScoringWeights()
    low = calculate_score(rows[0], weights, constant_factors=constant)
    high = calculate_score(rows[1], weights, constant_factors=constant)
    assert high > low
    # renormalize: quota 0.30 / (1.0-0.10-0.25-0.20-0.15 wait remaining = quota+tier_fit = 0.45)
    # health and latency also constant → dropped too
    assert "health" in constant and "latency_inv" in constant and "tier_fit" in constant
    assert abs(high - (0.8)) < 1e-9
    assert abs(low - (0.2)) < 1e-9


def test_factors_for_unknown_quota_is_one():
    factors = factors_for(_cand(), tier="standard", quota_reader=None, health_reader=None)
    assert factors.quota == 1.0
    assert factors.health == 1.0
    assert factors.latency_inv == 1.0


def test_d9_signatures_forbid_ain_routing():
    forbidden = {
        "tier_routing",
        "routing_prior",
        "provider_order",
        "preferred_providers",
        "prompt",
        "messages",
        "monthly_tokens",
    }
    assert forbidden.isdisjoint(inspect.signature(factors_for).parameters)
    assert forbidden.isdisjoint(inspect.signature(calculate_score).parameters)
    assert forbidden.isdisjoint(inspect.signature(tier_fit_for).parameters)
