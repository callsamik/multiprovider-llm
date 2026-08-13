# multiprovider-llm v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a working private `multiprovider_llm` package with sync/async `complete`/`acomplete`, three adapters (OpenAI-compat, Anthropic, Gemini), tier/fallback routing, thread- and async-safe in-memory limiter + cooldowns, and unit/mock tests — no AIN coupling.

**Architecture:** Orchestration (`Client` / `AsyncClient`) owns routing, freshness filtering, retry classification, cooldowns, and budgets. Adapters implement a shared `ProviderAdapter` protocol over `httpx` (sync + native async). Config and `Limiter` stay labeled experimental.

**Tech Stack:** Python `>=3.11,<4`, `httpx>=0.27,<1`, pytest, pytest-asyncio, respx; hatchling build; package under `src/multiprovider_llm/`.

**Spec:** [`docs/design.md`](design.md) (approved).

## Global Constraints

- Python `>=3.11,<4`; dependency `httpx>=0.27,<1`; no vendor SDKs required.
- Import package name: `multiprovider_llm`; distribution name: `multiprovider-llm`.
- Do **not** modify or depend on Autonomous Investment Navigator.
- Explicit `provider_chain` **overrides** tier routing entirely.
- `json_schema` only allowed when `response_format="json"`.
- `include_raw=False` by default; never put full raw payloads on error paths; truncate/sanitize error bodies.
- Timeout field name: `timeout_s`.
- Distinct errors: `NoEligibleProviders` (zero attempts) vs `AllProvidersFailed` (≥1 attempt).
- Limiter: atomic reserve → finalize on success / release on failure; thread-safe and async-safe; in-memory default.
- Async uses native `httpx.AsyncClient` (no `asyncio.to_thread` for the hot path).
- Lazy provider registration; duplicate names rejected unless `replace=True`.
- Config schema, `Limiter` protocol, and hooks are **experimental** (README-labeled).
- Live tests (`@pytest.mark.live`) are opt-in and excluded from required CI.
- Groq / OpenRouter / Ollama presets are **out of v1** (OpenAI-compat adapter supports OpenAI only for now).

## File map

| Path | Responsibility |
| :--- | :--- |
| `src/multiprovider_llm/errors.py` | Typed exceptions |
| `src/multiprovider_llm/types.py` | `Message`, `Usage`, `AttemptRecord`, `CompletionResult`, `ProviderRequest`, `ProviderResponse`, config dataclasses |
| `src/multiprovider_llm/protocols.py` | `Limiter`, `Reservation`, `ProviderAdapter` |
| `src/multiprovider_llm/serialization.py` | Message normalize; JSON extract for `response_format="json"` |
| `src/multiprovider_llm/limits.py` | In-memory limiter + cooldown store |
| `src/multiprovider_llm/routing.py` | Chain resolve, freshness filter, model resolve, retryability |
| `src/multiprovider_llm/config.py` | Load dict/JSON → `LibraryConfig` (experimental) |
| `src/multiprovider_llm/client.py` | Sync `Client.complete` |
| `src/multiprovider_llm/async_client.py` | `AsyncClient.acomplete` |
| `src/multiprovider_llm/providers/base.py` | Shared HTTP helpers (truncate body, header parse) |
| `src/multiprovider_llm/providers/registry.py` | Lazy register / resolve |
| `src/multiprovider_llm/providers/openai_compat.py` | OpenAI Chat Completions |
| `src/multiprovider_llm/providers/anthropic.py` | Anthropic Messages |
| `src/multiprovider_llm/providers/gemini.py` | Gemini `generateContent` |
| `src/multiprovider_llm/__init__.py` | Public exports |
| `tests/…` | Mirror modules above |

---

### Task 1: Errors + core types

**Files:**
- Create: `src/multiprovider_llm/errors.py`
- Create: `src/multiprovider_llm/types.py`
- Create: `tests/test_types.py`
- Modify: `src/multiprovider_llm/__init__.py` (export errors/types incrementally as they stabilize; minimum: `__version__` stays)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `ValidationError`, `ConfigError`, `ProviderError`, `RateLimited`, `NoEligibleProviders`, `AllProvidersFailed`
  - `Message(role: str, content: str)`
  - `Usage(prompt_tokens: int | None, completion_tokens: int | None, total_tokens: int | None, extras: Mapping[str, Any])`
  - `AttemptRecord`, `CompletionResult`
  - `ProviderRequest`, `ProviderResponse`

- [ ] **Step 1: Install editable package + dev deps**

```bash
cd /Users/callsamik/Projects/multiprovider-llm
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: install succeeds; `python -c "import multiprovider_llm; print(multiprovider_llm.__version__)"` prints `0.1.0a1`.

- [ ] **Step 2: Write failing tests for errors and types**

```python
# tests/test_types.py
from multiprovider_llm.errors import (
    AllProvidersFailed,
    NoEligibleProviders,
    ProviderError,
    ValidationError,
)
from multiprovider_llm.types import (
    AttemptRecord,
    CompletionResult,
    Message,
    ProviderRequest,
    ProviderResponse,
    Usage,
)


def test_no_eligible_distinct_from_all_failed():
    assert NoEligibleProviders is not AllProvidersFailed
    assert issubclass(NoEligibleProviders, Exception)
    assert issubclass(AllProvidersFailed, Exception)


def test_provider_error_truncation_fields():
    err = ProviderError("boom", status_code=500, body="x" * 5000, headers={"a": "1"})
    assert err.status_code == 500
    assert len(err.body) <= 500
    assert err.headers == {"a": "1"}


def test_usage_extras_and_completion_result_defaults():
    usage = Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3, extras={"cache": 9})
    result = CompletionResult(
        text="{}",
        provider="openai",
        model="gpt-4.1-mini",
        tier="simple",
        latency_ms=12.5,
        usage=usage,
        attempts=(AttemptRecord(
            provider="openai",
            model="gpt-4.1-mini",
            ok=True,
            error_type=None,
            status_code=200,
            latency_ms=12.5,
            message=None,
        ),),
        raw=None,
    )
    assert result.raw is None
    assert result.usage.extras["cache"] == 9


def test_provider_request_uses_timeout_s():
    req = ProviderRequest(
        messages=(Message(role="user", content="hi"),),
        model="m",
        timeout_s=5.0,
        response_format="text",
        json_schema=None,
        include_raw=False,
        extras={},
    )
    assert req.timeout_s == 5.0
    assert not hasattr(req, "timeout") or not callable(getattr(req, "timeout", None))
```

- [ ] **Step 3: Run tests — expect fail**

```bash
pytest tests/test_types.py -v
```

Expected: FAIL (modules/imports missing).

- [ ] **Step 4: Implement errors + types**

```python
# src/multiprovider_llm/errors.py
from __future__ import annotations

from typing import Any, Mapping, Sequence


class MultiproviderError(Exception):
    """Base error for multiprovider-llm."""


class ValidationError(MultiproviderError):
    pass


class ConfigError(MultiproviderError):
    pass


class ProviderError(MultiproviderError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        headers: Mapping[str, Any] | None = None,
        body: str = "",
        provider: str | None = None,
    ) -> None:
        truncated = body if len(body) <= 500 else body[:500]
        super().__init__(message)
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.body = truncated
        self.provider = provider


class RateLimited(ProviderError):
    pass


class NoEligibleProviders(MultiproviderError):
    """Chain empty after filters — no HTTP attempts were made."""


class AllProvidersFailed(MultiproviderError):
    """At least one provider was attempted; all failed."""

    def __init__(self, message: str, *, attempts: Sequence[Any] = ()) -> None:
        super().__init__(message)
        self.attempts = tuple(attempts)
```

```python
# src/multiprovider_llm/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence


Role = str
ResponseFormat = Literal["text", "json"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AttemptRecord:
    provider: str
    model: str | None
    ok: bool
    error_type: str | None
    status_code: int | None
    latency_ms: float
    message: str | None


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    tier: str | None
    latency_ms: float
    usage: Usage
    attempts: tuple[AttemptRecord, ...]
    raw: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ProviderRequest:
    messages: tuple[Message, ...]
    model: str
    timeout_s: float | None
    response_format: ResponseFormat
    json_schema: Mapping[str, Any] | None
    include_raw: bool
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    usage: Usage
    status_code: int
    headers: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] | None = None
```

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/test_types.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/multiprovider_llm/errors.py src/multiprovider_llm/types.py tests/test_types.py
git commit -m "feat: add core errors and result types"
```

---

### Task 2: Protocols + serialization

**Files:**
- Create: `src/multiprovider_llm/protocols.py`
- Create: `src/multiprovider_llm/serialization.py`
- Create: `tests/test_serialization.py`

**Interfaces:**
- Consumes: `Message`, `Usage`, `ValidationError`, `ProviderRequest`/`ProviderResponse` types
- Produces:
  - `Reservation` protocol/dataclass; `Limiter` protocol with `try_reserve` / `finalize` / `release`
  - `ProviderAdapter` protocol with `name`, `complete`, `acomplete`
  - `normalize_messages(prompt=None, messages=None) -> list[Message]`
  - `extract_json_text(text: str) -> str` (returns JSON object string or raises `ValidationError`)

- [ ] **Step 1: Write failing serialization tests**

```python
# tests/test_serialization.py
import pytest

from multiprovider_llm.errors import ValidationError
from multiprovider_llm.serialization import extract_json_text, normalize_messages
from multiprovider_llm.types import Message


def test_normalize_prompt_only():
    msgs = normalize_messages(prompt="hello", messages=None)
    assert msgs == [Message(role="user", content="hello")]


def test_normalize_mapping_messages():
    msgs = normalize_messages(
        prompt=None,
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
    )
    assert msgs[0].role == "system" and msgs[1].content == "u"


def test_normalize_rejects_both_or_neither():
    with pytest.raises(ValidationError):
        normalize_messages(prompt="x", messages=[Message("user", "y")])
    with pytest.raises(ValidationError):
        normalize_messages(prompt=None, messages=None)


def test_extract_json_from_fence_and_think():
    raw = "<think>nope</think>```json\n{\"a\": 1}\n```"
    assert extract_json_text(raw) == '{"a": 1}' or '"a"' in extract_json_text(raw)


def test_extract_json_fails_on_plain_text():
    with pytest.raises(ValidationError):
        extract_json_text("not json")
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_serialization.py -v
```

- [ ] **Step 3: Implement protocols + serialization**

```python
# src/multiprovider_llm/protocols.py
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import ProviderRequest, ProviderResponse, Usage


@runtime_checkable
class Reservation(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def token_estimate(self) -> int | None: ...


@runtime_checkable
class Limiter(Protocol):
    def try_reserve(self, provider: str, *, tokens: int | None = None) -> Reservation: ...

    def finalize(self, reservation: Reservation, *, usage: Usage) -> None: ...

    def release(self, reservation: Reservation) -> None: ...


@runtime_checkable
class ProviderAdapter(Protocol):
    name: str

    def complete(self, req: ProviderRequest) -> ProviderResponse: ...

    async def acomplete(self, req: ProviderRequest) -> ProviderResponse: ...
```

```python
# src/multiprovider_llm/serialization.py
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from .errors import ValidationError
from .types import Message


def normalize_messages(
    *,
    prompt: str | None,
    messages: Sequence[Message | Mapping[str, Any]] | None,
) -> list[Message]:
    if prompt is not None and messages is not None:
        raise ValidationError("provide exactly one of prompt or messages")
    if prompt is None and messages is None:
        raise ValidationError("provide exactly one of prompt or messages")
    if prompt is not None:
        return [Message(role="user", content=str(prompt))]
    out: list[Message] = []
    for item in messages or ():
        if isinstance(item, Message):
            out.append(item)
            continue
        role = str(item.get("role", "")).strip()
        content = item.get("content")
        if not role or content is None:
            raise ValidationError("each message mapping needs role and content")
        out.append(Message(role=role, content=str(content)))
    if not out:
        raise ValidationError("messages must be non-empty")
    return out


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_text(text: str) -> str:
    raw = _THINK_RE.sub("", text or "")
    raw = _THINK_OPEN_RE.sub("", raw).strip()
    if not raw:
        raise ValidationError("empty model response")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return json.dumps(data, separators=(",", ":"))
    except json.JSONDecodeError:
        pass
    fence = _FENCE_RE.search(raw)
    if fence:
        data = json.loads(fence.group(1))
        if isinstance(data, dict):
            return json.dumps(data, separators=(",", ":"))
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(raw[start : end + 1])
        if isinstance(data, dict):
            return json.dumps(data, separators=(",", ":"))
    raise ValidationError("model response was not a JSON object")
```

Also add a concrete `MemoryReservation` dataclass in `limits.py` later; for Task 2, protocols alone are enough. Add a tiny test that `ProviderAdapter` is a Protocol (optional).

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_serialization.py tests/test_types.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/protocols.py src/multiprovider_llm/serialization.py tests/test_serialization.py
git commit -m "feat: add protocols and message/JSON serialization"
```

---

### Task 3: Registry + OpenAI-compatible adapter

**Files:**
- Create: `src/multiprovider_llm/providers/base.py`
- Create: `src/multiprovider_llm/providers/registry.py`
- Create: `src/multiprovider_llm/providers/openai_compat.py`
- Create: `tests/test_registry.py`
- Create: `tests/test_openai_compat.py`

**Interfaces:**
- Consumes: `ProviderAdapter`, `ProviderRequest`, `ProviderResponse`, `ProviderError`, `RateLimited`, `Usage`
- Produces:
  - `register_provider(name, factory, *, replace=False)`, `get_provider(name) -> ProviderAdapter`, `ensure_builtins_loaded()`
  - `OpenAICompatAdapter(name="openai", api_key=..., base_url=...)`
  - Reserved `extras` keys documented in module docstring: adapters ignore unknown keys; must not reinterpret `model`, `messages`, `timeout_s`, `response_format`, `json_schema`

- [ ] **Step 1: Write failing registry + openai tests**

```python
# tests/test_registry.py
import pytest

from multiprovider_llm.errors import ConfigError
from multiprovider_llm.providers import registry


def test_duplicate_registration_rejected():
    registry._clear_for_tests()
    registry.register_provider("openai", lambda: object())
    with pytest.raises(ConfigError):
        registry.register_provider("openai", lambda: object())
    registry.register_provider("openai", lambda: object(), replace=True)


def test_invalid_name_rejected():
    registry._clear_for_tests()
    with pytest.raises(ConfigError):
        registry.register_provider("bad name!", lambda: object())
```

```python
# tests/test_openai_compat.py
import httpx
import respx

from multiprovider_llm.providers.openai_compat import OpenAICompatAdapter
from multiprovider_llm.types import Message, ProviderRequest


@respx.mock
def test_openai_chat_completion_ok():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        )
    )
    adapter = OpenAICompatAdapter(api_key="sk-test", base_url="https://api.openai.com/v1")
    req = ProviderRequest(
        messages=(Message("user", "hi"),),
        model="gpt-4.1-mini",
        timeout_s=10.0,
        response_format="json",
        json_schema=None,
        include_raw=False,
        extras={},
    )
    resp = adapter.complete(req)
    assert route.called
    assert resp.text
    assert resp.usage.total_tokens == 3
    assert resp.raw is None


@respx.mock
def test_openai_include_raw_and_rate_limit():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate"}}, headers={"retry-after": "1"})
    )
    adapter = OpenAICompatAdapter(api_key="sk-test")
    req = ProviderRequest(
        messages=(Message("user", "hi"),),
        model="m",
        timeout_s=5.0,
        response_format="text",
        json_schema=None,
        include_raw=True,
        extras={},
    )
    import pytest
    from multiprovider_llm.errors import RateLimited

    with pytest.raises(RateLimited) as ei:
        adapter.complete(req)
    assert len(ei.value.body) <= 500
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_registry.py tests/test_openai_compat.py -v
```

- [ ] **Step 3: Implement base helpers, registry, openai_compat**

Implement:

- `providers/base.py`: `truncate_body(text, limit=500)`, `raise_for_status(provider, response)` mapping 429→`RateLimited`, else `ProviderError`
- `providers/registry.py`: name regex `^[a-z][a-z0-9_]*$`; factory dict; lazy `ensure_builtins_loaded()` imports openai/anthropic/gemini modules and registers defaults **without** constructing adapters that need keys
- `providers/openai_compat.py`: POST `{base_url}/chat/completions` with `Authorization: Bearer …`, messages as OpenAI chat format; parse `choices[0].message.content` and usage; `include_raw` gates `raw=response.json()`; async twin with `httpx.AsyncClient`

Keep adapter construction key-based; registry stores factories used by `Client` later.

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_registry.py tests/test_openai_compat.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/providers/base.py src/multiprovider_llm/providers/registry.py src/multiprovider_llm/providers/openai_compat.py tests/test_registry.py tests/test_openai_compat.py
git commit -m "feat: add provider registry and OpenAI-compatible adapter"
```

---

### Task 4: Anthropic + Gemini adapters

**Files:**
- Create: `src/multiprovider_llm/providers/anthropic.py`
- Create: `src/multiprovider_llm/providers/gemini.py`
- Create: `tests/test_anthropic.py`
- Create: `tests/test_gemini.py`
- Modify: `src/multiprovider_llm/providers/registry.py` (lazy builtin registration for `anthropic`, `gemini`)

**Interfaces:**
- Consumes: same adapter contract as OpenAI
- Produces: `AnthropicAdapter`, `GeminiAdapter` with sync+async `complete`/`acomplete`

- [ ] **Step 1: Write failing adapter tests (respx)**

Anthropic: `POST https://api.anthropic.com/v1/messages` with headers `x-api-key`, `anthropic-version: 2023-06-01`; body `max_tokens`, `model`, `messages`; parse `content[0].text`.

Gemini: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=…`; map roles (`user`/`model`); parse `candidates[0].content.parts[0].text`.

Each test: happy path + 401 stops as `ProviderError` + `include_raw=False` leaves `raw is None`.

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_anthropic.py tests/test_gemini.py -v
```

- [ ] **Step 3: Implement both adapters** (httpx only; ignore unknown `extras` keys; do not reinterpret reserved names)

- [ ] **Step 4: Run full adapter suite — expect pass**

```bash
pytest tests/test_openai_compat.py tests/test_anthropic.py tests/test_gemini.py tests/test_registry.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/providers/anthropic.py src/multiprovider_llm/providers/gemini.py src/multiprovider_llm/providers/registry.py tests/test_anthropic.py tests/test_gemini.py
git commit -m "feat: add Anthropic and Gemini HTTP adapters"
```

---

### Task 5: In-memory limiter + cooldowns

**Files:**
- Create: `src/multiprovider_llm/limits.py`
- Create: `tests/test_limits.py`

**Interfaces:**
- Consumes: `Limiter` protocol, `Usage`
- Produces:
  - `MemoryReservation(provider: str, token_estimate: int | None)`
  - `InMemoryLimiter(per_provider: Mapping[str, ProviderLimit], global_budget: int | None = None)`
  - `ProviderLimit(max_inflight: int, max_tokens_per_minute: int | None = None)` (keep simple: at least `max_inflight` + optional global count)
  - `CooldownTracker` with `set_cooldown(provider, until_monotonic)`, `is_cooling(provider) -> bool`
  - All mutations under a `threading.Lock` (safe for threads and asyncio tasks in one process)

Semantics:

1. `try_reserve` atomically increments inflight (and global if set); if over cap raise `RateLimited` or a small `BudgetExceeded` — prefer raising `RateLimited` for provider cap and a dedicated `BudgetExceeded(MultiproviderError)` for global exhaustion so orchestration can continue or stop per policy. **Spec choice for v1:** provider cap → skip provider (treat as retryable continue); global budget exhausted → raise `NoEligibleProviders`-ineligible for remaining? Better: raise `RateLimited(provider="*")` only for that call's reserve failure and let orchestrator **continue** to next provider for per-provider denies; if global budget cannot reserve, **stop** with a `BudgetExceeded` that orchestrator maps to failing the call without pretending providers were attempted… Spec says reserve before call. Implement:

- Per-provider deny → orchestrator skips to next (no attempt record HTTP, optional attempt record `error_type="budget"`).
- Global deny → raise `BudgetExceeded` before attempts if no reservation possible at all for any; if mid-chain, stop with `BudgetExceeded`.

Add `BudgetExceeded` to `errors.py` in this task.

- [ ] **Step 1: Write concurrency tests**

```python
# tests/test_limits.py
import threading
import time

import pytest

from multiprovider_llm.errors import BudgetExceeded, RateLimited
from multiprovider_llm.limits import CooldownTracker, InMemoryLimiter, ProviderLimit
from multiprovider_llm.types import Usage


def test_reserve_finalize_release():
    lim = InMemoryLimiter(
        per_provider={"openai": ProviderLimit(max_inflight=1)},
        global_budget=2,
    )
    r = lim.try_reserve("openai", tokens=1)
    with pytest.raises(RateLimited):
        lim.try_reserve("openai", tokens=1)
    lim.finalize(r, usage=Usage(total_tokens=1))
    r2 = lim.try_reserve("openai", tokens=1)
    lim.release(r2)


def test_global_budget():
    lim = InMemoryLimiter(
        per_provider={"a": ProviderLimit(max_inflight=10), "b": ProviderLimit(max_inflight=10)},
        global_budget=1,
    )
    r = lim.try_reserve("a")
    with pytest.raises(BudgetExceeded):
        lim.try_reserve("b")
    lim.release(r)


def test_threaded_reserves():
    lim = InMemoryLimiter(per_provider={"x": ProviderLimit(max_inflight=5)}, global_budget=5)
    ok = []
    err = []

    def worker():
        try:
            r = lim.try_reserve("x")
            time.sleep(0.01)
            lim.release(r)
            ok.append(1)
        except Exception as e:  # noqa: BLE001
            err.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) + len(err) == 20
    assert len(ok) >= 5


def test_cooldown():
    cd = CooldownTracker()
    cd.set_cooldown("groq", seconds=0.05)
    assert cd.is_cooling("groq")
    time.sleep(0.06)
    assert not cd.is_cooling("groq")
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_limits.py -v
```

- [ ] **Step 3: Implement `limits.py` + `BudgetExceeded`**

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_limits.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/limits.py src/multiprovider_llm/errors.py tests/test_limits.py
git commit -m "feat: add thread-safe in-memory limiter and cooldowns"
```

---

### Task 6: Routing + retryability

**Files:**
- Create: `src/multiprovider_llm/routing.py`
- Create: `src/multiprovider_llm/config.py` (minimal dataclasses needed by routing)
- Create: `tests/test_routing.py`

**Interfaces:**
- Consumes: config provider descriptors
- Produces:
  - `@dataclass ProviderConfig`: `name`, `enabled`, `freshness_ok`, `models: dict[str, str]`, `default_model: str`, `rate_limits`, `base_url`, `api_key_env`
  - `@dataclass LibraryConfig`: `providers: dict[str, ProviderConfig]`, `provider_order: tuple[str, ...]`, `tier_routing: dict[str, tuple[str, ...]]`, `global_budget: int | None`
  - `resolve_chain(config, *, tier, provider_chain, freshness_required) -> tuple[str, ...]`
  - `resolve_model(config, provider, tier) -> str`
  - `is_retryable(exc: BaseException) -> bool` — True for `RateLimited`, timeouts (`httpx.TimeoutException`), connect errors, `ProviderError` with status in `{429,500,502,503,504}`; False for auth `401/403`, validation `400`, `ValidationError`, `ConfigError`

- [ ] **Step 1: Write failing routing tests**

```python
# tests/test_routing.py
from multiprovider_llm.config import LibraryConfig, ProviderConfig
from multiprovider_llm.routing import resolve_chain, resolve_model, is_retryable
from multiprovider_llm.errors import ProviderError, RateLimited, ValidationError


def _cfg():
    return LibraryConfig(
        providers={
            "openai": ProviderConfig(
                name="openai",
                enabled=True,
                freshness_ok=True,
                models={"simple": "gpt-small", "standard": "gpt-mid", "complex": "gpt-big"},
                default_model="gpt-mid",
                base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
            "ollama": ProviderConfig(
                name="ollama",
                enabled=True,
                freshness_ok=False,
                models={},
                default_model="qwen",
                base_url="http://localhost:11434/v1",
                api_key_env="",
            ),
            "anthropic": ProviderConfig(
                name="anthropic",
                enabled=True,
                freshness_ok=True,
                models={"standard": "claude"},
                default_model="claude",
                base_url="https://api.anthropic.com",
                api_key_env="ANTHROPIC_API_KEY",
            ),
        },
        provider_order=("openai", "anthropic", "ollama"),
        tier_routing={"standard": ("anthropic", "openai")},
        global_budget=None,
    )


def test_explicit_chain_overrides_tier():
    chain = resolve_chain(
        _cfg(), tier="standard", provider_chain=("openai",), freshness_required=False
    )
    assert chain == ("openai",)


def test_tier_routing_reorders():
    chain = resolve_chain(_cfg(), tier="standard", provider_chain=None, freshness_required=False)
    assert chain[0] == "anthropic"
    assert "openai" in chain


def test_freshness_filters_local():
    chain = resolve_chain(_cfg(), tier=None, provider_chain=None, freshness_required=True)
    assert "ollama" not in chain


def test_retryability_matrix():
    assert is_retryable(RateLimited("x", status_code=429))
    assert is_retryable(ProviderError("x", status_code=503))
    assert not is_retryable(ProviderError("x", status_code=401))
    assert not is_retryable(ValidationError("bad"))
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_routing.py -v
```

- [ ] **Step 3: Implement `config.py` dataclasses + `routing.py`**

`resolve_chain` must not invent providers absent from `provider_order` / enabled set when applying tier routing (same semantics as design: preferred lead, remainder keep relative order). Disabled providers omitted. Empty result is allowed here; `Client` turns empty into `NoEligibleProviders`.

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_routing.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/config.py src/multiprovider_llm/routing.py tests/test_routing.py
git commit -m "feat: add config dataclasses and provider chain routing"
```

---

### Task 7: Sync `Client.complete`

**Files:**
- Create: `src/multiprovider_llm/client.py`
- Create: `tests/test_client.py`
- Modify: `src/multiprovider_llm/__init__.py` — export `Client`, errors, `CompletionResult`

**Interfaces:**
- Consumes: routing, limits, serialization, registry/adapters
- Produces:

```python
class Client:
    def __init__(
        self,
        config: LibraryConfig,
        *,
        limiter: Limiter | None = None,
        cooldowns: CooldownTracker | None = None,
        adapters: Mapping[str, ProviderAdapter] | None = None,
    ) -> None: ...

    def complete(
        self,
        *,
        prompt: str | None = None,
        messages: Sequence[Message | Mapping[str, Any]] | None = None,
        tier: str | None = None,
        provider_chain: Sequence[str] | None = None,
        response_format: Literal["text", "json"] = "text",
        json_schema: Mapping[str, Any] | None = None,
        freshness_required: bool = False,
        timeout_s: float | None = None,
        include_raw: bool = False,
    ) -> CompletionResult: ...
```

Orchestration must match design §5–§6 exactly.

- [ ] **Step 1: Write failing client tests with fake adapters**

```python
# tests/test_client.py
import pytest

from multiprovider_llm.client import Client
from multiprovider_llm.config import LibraryConfig, ProviderConfig
from multiprovider_llm.errors import (
    AllProvidersFailed,
    NoEligibleProviders,
    ProviderError,
    RateLimited,
    ValidationError,
)
from multiprovider_llm.types import ProviderRequest, ProviderResponse, Usage


class FakeAdapter:
    def __init__(self, name: str, behavior):
        self.name = name
        self.behavior = behavior

    def complete(self, req: ProviderRequest) -> ProviderResponse:
        return self.behavior(req)

    async def acomplete(self, req: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError


def _config(order=("a", "b")):
    providers = {
        n: ProviderConfig(
            name=n,
            enabled=True,
            freshness_ok=True,
            models={"standard": "m"},
            default_model="m",
            base_url="",
            api_key_env="",
        )
        for n in order
    }
    return LibraryConfig(
        providers=providers,
        provider_order=order,
        tier_routing={},
        global_budget=None,
    )


def test_json_schema_requires_json_format():
    client = Client(_config(), adapters={})
    with pytest.raises(ValidationError):
        client.complete(prompt="x", response_format="text", json_schema={"type": "object"})


def test_no_eligible_providers():
    cfg = _config(order=("local",))
    cfg.providers["local"] = ProviderConfig(
        name="local",
        enabled=True,
        freshness_ok=False,
        models={},
        default_model="m",
        base_url="",
        api_key_env="",
    )
    client = Client(cfg, adapters={})
    with pytest.raises(NoEligibleProviders):
        client.complete(prompt="x", freshness_required=True)


def test_fallback_then_success():
    def fail(_req):
        raise RateLimited("no", status_code=429, provider="a")

    def ok(_req):
        return ProviderResponse(text='{"ok":true}', usage=Usage(total_tokens=1), status_code=200)

    client = Client(
        _config(("a", "b")),
        adapters={"a": FakeAdapter("a", fail), "b": FakeAdapter("b", ok)},
    )
    result = client.complete(prompt="hi", response_format="json")
    assert result.provider == "b"
    assert len(result.attempts) == 2
    assert result.attempts[0].ok is False and result.attempts[1].ok is True


def test_auth_stops_chain():
    def auth(_req):
        raise ProviderError("auth", status_code=401, provider="a")

    def ok(_req):
        return ProviderResponse(text="y", usage=Usage(), status_code=200)

    client = Client(
        _config(("a", "b")),
        adapters={"a": FakeAdapter("a", auth), "b": FakeAdapter("b", ok)},
    )
    with pytest.raises(ProviderError):
        client.complete(prompt="hi")


def test_all_providers_failed():
    def fail(req):
        raise RateLimited("no", status_code=429)

    client = Client(
        _config(("a", "b")),
        adapters={"a": FakeAdapter("a", fail), "b": FakeAdapter("b", fail)},
    )
    with pytest.raises(AllProvidersFailed) as ei:
        client.complete(prompt="hi")
    assert len(ei.value.attempts) == 2
```

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_client.py -v
```

- [ ] **Step 3: Implement `Client.complete`**

Important details:

- Validate `json_schema` vs `response_format` first.
- `normalize_messages` then `resolve_chain`; empty → `NoEligibleProviders`.
- For each provider: skip if cooling; `try_reserve`; on per-provider `RateLimited` from limiter, continue; on `BudgetExceeded`, raise; call adapter; on retryable error `release`, append attempt, set cooldown if rate limit, continue; on non-retryable `release` and re-raise; on success `finalize`, optionally `extract_json_text` when `response_format=="json"`, return `CompletionResult` with `raw` only if `include_raw`.
- Wall-clock `latency_ms` on result = sum or total call time (document: total orchestration time).

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_client.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/client.py src/multiprovider_llm/__init__.py tests/test_client.py
git commit -m "feat: add sync Client.complete orchestration"
```

---

### Task 8: `AsyncClient.acomplete`

**Files:**
- Create: `src/multiprovider_llm/async_client.py`
- Create: `tests/test_async_client.py`
- Modify: `src/multiprovider_llm/__init__.py` — export `AsyncClient`

**Interfaces:**
- Same kwargs as `Client.complete`; uses `adapter.acomplete`; limiter/cooldowns shared (lock-safe).

- [ ] **Step 1: Write async fallback test with fake async adapters**

```python
# tests/test_async_client.py
import pytest

from multiprovider_llm.async_client import AsyncClient
from multiprovider_llm.types import ProviderRequest, ProviderResponse, Usage
# reuse _config / Fake pattern with async complete
```

Include one test that two concurrent `acomplete` calls respect `max_inflight=1` via `InMemoryLimiter`.

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_async_client.py -v
```

- [ ] **Step 3: Implement `AsyncClient`** — prefer sharing private orchestration helpers with `client.py` (e.g. `_prepare_call`, `_handle_success`) to avoid drift; async loop calls `await adapter.acomplete`.

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_async_client.py tests/test_client.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/async_client.py src/multiprovider_llm/client.py src/multiprovider_llm/__init__.py tests/test_async_client.py
git commit -m "feat: add AsyncClient.acomplete with native async adapters"
```

---

### Task 9: Config loader + README + public exports

**Files:**
- Modify: `src/multiprovider_llm/config.py` — `load_config(path: str | Path) -> LibraryConfig`, `config_from_dict(data: Mapping) -> LibraryConfig`
- Create: `tests/test_config_load.py`
- Create: `examples/minimal_config.json`
- Modify: `README.md` — experimental callouts; working example using dict config + Fake or documented env keys
- Modify: `src/multiprovider_llm/__init__.py` — final exports list

**Interfaces:**
- JSON keys match experimental schema in design §9
- Missing required fields → `ConfigError`
- Unknown top-level keys ignored (forward compatible) OR rejected — **choose reject unknown top-level for v1 clarity**

- [ ] **Step 1: Write config load tests** with a temp JSON file enabling openai/anthropic/gemini

- [ ] **Step 2: Run — expect fail**

```bash
pytest tests/test_config_load.py -v
```

- [ ] **Step 3: Implement loader + update README**

README must state Experimental: config schema, Limiter, hooks. Document env vars: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (or `GOOGLE_API_KEY` — pick one name and stick to it in config `api_key_env`).

- [ ] **Step 4: Run full unit suite (exclude live)**

```bash
pytest -m "not live" -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/multiprovider_llm/config.py src/multiprovider_llm/__init__.py tests/test_config_load.py examples/minimal_config.json README.md
git commit -m "feat: add experimental config loader and document public API"
```

---

### Task 10: Plan/spec self-check gate (no new features)

**Files:** none new

- [ ] **Step 1: Map design.md sections to tests**

Manually verify coverage for: API validation, chain override, freshness, NoEligible vs AllFailed, retry matrix, raw privacy, limiter reserve/finalize, async parity, registry duplicates, truncated errors.

```bash
pytest -m "not live" -v
```

- [ ] **Step 2: Confirm non-goals absent**

Grep the tree for `ain`, `AutonomousInvestment`, `groq`, `openrouter`, `ollama` presets — only freshness example config names are OK; no AIN imports.

- [ ] **Step 3: Commit only if docs tweaks needed** (e.g. mark design Status: Implemented-partial)

```bash
git commit -m "docs: note v1 implementation complete against design.md"
```

(Skip empty commit if nothing changed.)

---

## Spec coverage checklist (plan author)

| Design section | Task(s) |
| :--- | :--- |
| Goals / non-goals | Global constraints; Task 10 |
| Runtime Python/httpx | Task 1 install; pyproject |
| Public API complete/acomplete | Tasks 7–8 |
| Message / json_schema / freshness / chain override | Tasks 2, 6, 7 |
| Usage / raw privacy | Tasks 1, 3, 7 |
| Orchestration flow | Task 7–8 |
| Retryability | Task 6–7 |
| Limiter + cooldown concurrency | Task 5 |
| Adapter contract + extras rules | Tasks 3–4 |
| Registry lazy/duplicates | Task 3 |
| Config experimental | Task 9 |
| Errors distinct | Tasks 1, 7 |
| Testing layers | Tasks 1–9; live deferred |
| No Groq/OR/Ollama v1 | Global constraints |
| No AIN | Global constraints; Task 10 |

## Placeholder scan

Plan avoids TBD/TODO implementation steps; Task 4 adapter request/response details are specified via concrete endpoints and parse paths. `BudgetExceeded` added in Task 5 as needed for global budget (compatible with design limiter section).

---

## Execution handoff

Plan complete and saved to `docs/plan.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

Which approach?
