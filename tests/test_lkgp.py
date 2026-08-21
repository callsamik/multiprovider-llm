from multiprovider_llm.routing.lkgp import LkgpStore
from multiprovider_llm.routing.types import RankedTarget, ScoringFactors


def _t(provider, score, rank):
    return RankedTarget(
        provider=provider,
        model="m",
        score=score,
        factors=ScoringFactors(1, 1, 1, 1, 1),
        rank=rank,
    )


def test_promote_within_band():
    store = LkgpStore(band=0.10)
    store.remember("standard:live_brief", "gemini", "m", now=1.0)
    ranked = (_t("groq", 1.0, 1), _t("gemini", 0.91, 2))
    out, promoted = store.promote(ranked, "standard:live_brief", now=2.0)
    assert promoted is True
    assert out[0].provider == "gemini"
    assert out[0].rank == 1
    assert out[1].provider == "groq"
    assert out[1].rank == 2


def test_no_promote_outside_band():
    store = LkgpStore(band=0.10)
    store.remember("k", "gemini", "m", now=1.0)
    ranked = (_t("groq", 1.0, 1), _t("gemini", 0.80, 2))
    out, promoted = store.promote(ranked, "k", now=2.0)
    assert promoted is False
    assert out[0].provider == "groq"


def test_forget_and_ttl():
    store = LkgpStore(band=0.10, ttl_s=10.0)
    store.remember("k", "gemini", "m", now=1.0)
    store.forget("k")
    assert store.get("k", now=2.0) is None
    store.remember("k", "gemini", "m", now=1.0)
    assert store.get("k", now=12.0) is None
