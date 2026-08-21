from multiprovider_llm.resilience.model_lockout import ModelLockoutTracker
from multiprovider_llm.routing.prefilter import prefilter_candidates
from multiprovider_llm.routing.types import Candidate


def _c(provider="groq", model="m", adapter="openai_compat"):
    return Candidate(
        provider=provider,
        model=model,
        adapter=adapter,
        base_url="https://example.test",
        cost_tier="free",
        freshness_ok=True,
        tier_affinity={"standard": 1.0},
        http_referer=None,
    )


class Quota:
    def __init__(self, table):
        self.table = table

    def quota_remaining_pct(self, provider, model):
        return self.table.get((provider, model))


class Cool:
    def __init__(self, cooling):
        self.cooling = cooling

    def is_cooling(self, provider):
        return provider in self.cooling

    def remaining_seconds(self, provider):
        return 9.0 if provider in self.cooling else 0.0


def test_lockout_excludes():
    lockout = ModelLockoutTracker()
    lockout.lock("groq", "m", 30.0, now=1.0)
    result = prefilter_candidates((_c(), _c(provider="gemini", model="flash", adapter="gemini")), lockout=lockout, now=2.0)
    assert [c.provider for c in result.eligible] == ["gemini"]
    assert result.notes[0].reason == "lockout"


def test_cooldown_reader_excludes_provider():
    result = prefilter_candidates((_c(),), lockout=ModelLockoutTracker(), cooldown_reader=Cool({"groq"}))
    assert result.eligible == ()
    assert result.notes[0].reason == "cooldown"


def test_quota_cutoff_skips_known_low_keeps_unknown():
    groq = _c()
    gem = _c(provider="gemini", model="flash", adapter="gemini")
    result = prefilter_candidates(
        (groq, gem),
        lockout=ModelLockoutTracker(),
        quota_reader=Quota({("groq", "m"): 0.01, ("gemini", "flash"): None}),
        min_quota_pct=0.05,
    )
    assert [c.provider for c in result.eligible] == ["gemini"]
    assert result.notes[0].reason == "quota_cutoff"


def test_missing_adapter():
    result = prefilter_candidates(
        (_c(adapter="openai_compat"),),
        lockout=ModelLockoutTracker(),
        known_adapters=frozenset({"gemini"}),
    )
    assert result.eligible == ()
    assert result.notes[0].reason == "missing_adapter"
