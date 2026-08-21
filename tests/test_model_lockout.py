from multiprovider_llm.resilience.model_lockout import ModelLockoutTracker


def test_lock_expires():
    tracker = ModelLockoutTracker()
    tracker.lock("groq", "llama-3.1-8b-instant", 10.0, now=100.0)
    assert tracker.is_locked("groq", "llama-3.1-8b-instant", now=105.0)
    assert tracker.is_locked("groq", "llama-3.1-8b-instant", now=110.0) is False
    assert tracker.is_locked("groq", "other-model", now=105.0) is False
    assert tracker.is_locked("gemini", "llama-3.1-8b-instant", now=105.0) is False


def test_terminal_lock_never_expires():
    tracker = ModelLockoutTracker()
    tracker.lock("groq", "missing", None, now=1.0)
    assert tracker.is_locked("groq", "missing", now=10**9)
    assert tracker.remaining_seconds("groq", "missing", now=2.0) == float("inf")


def test_remaining_seconds():
    tracker = ModelLockoutTracker()
    tracker.lock("groq", "m", 8.0, now=10.0)
    assert tracker.remaining_seconds("groq", "m", now=12.0) == 6.0
    assert tracker.remaining_seconds("groq", "m", now=20.0) == 0.0
