import inspect

from multiprovider_llm.resilience.model_lockout import ModelLockoutTracker
from multiprovider_llm.routing.lkgp import LkgpStore
from multiprovider_llm.routing.rank import rank_candidates
from multiprovider_llm.routing.types import Candidate


def _c(provider, model, affinity, cost_tier="free"):
    return Candidate(
        provider=provider,
        model=model,
        adapter="openai_compat",
        base_url="https://example.test",
        cost_tier=cost_tier,
        freshness_ok=True,
        tier_affinity=affinity,
        http_referer=None,
    )


class Quota:
    def __init__(self, table):
        self.table = table

    def quota_remaining_pct(self, provider, model):
        return self.table.get((provider, model), 1.0)


def test_ranks_by_quota_and_tier_fit_not_input_order():
    groq = _c("groq", "8b", {"standard": 0.2})
    gemini = _c("gemini", "flash", {"standard": 1.0})
    result = rank_candidates(
        (groq, gemini),
        tier="standard",
        task_kind="live_brief",
        lockout=ModelLockoutTracker(),
        lkgp=LkgpStore(),
        quota_reader=Quota({("groq", "8b"): 0.1, ("gemini", "flash"): 0.9}),
    )
    assert [t.provider for t in result.ranked_targets] == ["gemini", "groq"]
    reversed_input = rank_candidates(
        (gemini, groq),
        tier="standard",
        task_kind="live_brief",
        lockout=ModelLockoutTracker(),
        lkgp=LkgpStore(),
        quota_reader=Quota({("groq", "8b"): 0.1, ("gemini", "flash"): 0.9}),
    )
    assert [t.provider for t in reversed_input.ranked_targets] == ["gemini", "groq"]
    assert result.diagnostics.pool_size == 2
    assert result.diagnostics.filtered_size == 2


def test_lockout_shows_in_diagnostics():
    lockout = ModelLockoutTracker()
    lockout.lock("groq", "8b", 30.0, now=1.0)
    result = rank_candidates(
        (_c("groq", "8b", {"standard": 1.0}), _c("gemini", "flash", {"standard": 1.0})),
        tier="standard",
        task_kind=None,
        lockout=lockout,
        lkgp=LkgpStore(),
        now=2.0,
    )
    assert [t.provider for t in result.ranked_targets] == ["gemini"]
    assert result.diagnostics.filter_notes[0].reason == "lockout"


def test_lkgp_promotion_recorded():
    store = LkgpStore(band=0.10)
    store.remember("standard:live_brief", "groq", "8b", now=1.0)
    result = rank_candidates(
        (
            _c("gemini", "flash", {"standard": 1.0}),
            _c("groq", "8b", {"standard": 1.0}),
        ),
        tier="standard",
        task_kind="live_brief",
        lockout=ModelLockoutTracker(),
        lkgp=store,
        quota_reader=Quota({("gemini", "flash"): 1.0, ("groq", "8b"): 0.95}),
        now=2.0,
    )
    assert result.diagnostics.lkgp_promoted is True
    assert result.ranked_targets[0].provider == "groq"


def test_rank_signature_forbids_policy_leaks():
    forbidden = {
        "tier_routing",
        "routing_prior",
        "provider_order",
        "preferred_providers",
        "prompt",
        "messages",
        "routing_mode",
        "monthly_tokens",
    }
    assert forbidden.isdisjoint(inspect.signature(rank_candidates).parameters)
