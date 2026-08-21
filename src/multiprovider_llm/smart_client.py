"""Experimental ranked-execution client (M4).

Frozen ``Client`` stays chain-only. This class consumes ``rank_candidates``
and ``classify_error``; it does not call ``Client.complete()``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from .catalog.credentials import CredentialResolver, EnvCredentialResolver
from .catalog.provider_catalog import ProviderCatalog, ProviderCatalogEntry, load_catalog
from .errors import (
    AllProvidersFailed,
    BudgetExceeded,
    ConfigError,
    MultiproviderError,
    NoEligibleProviders,
    RateLimited,
    ValidationError,
)
from .limits import InMemoryLimiter, ProviderLimit
from .protocols import CompletionHooks, HealthMetricsReader, Limiter, ProviderAdapter, QuotaReader, CooldownReader
from .resilience.error_classifier import classify_error
from .resilience.model_lockout import ModelLockoutTracker
from .routing.adapter_factory import adapter_for
from .routing.lkgp import LkgpStore
from .routing.metrics import RollingHealthMetrics
from .routing.pool import build_candidate_pool, default_enabled_providers
from .routing.rank import rank_candidates
from .routing.types import Candidate, RoutingDiagnostics
from .serialization import extract_json_text, normalize_messages
from .types import (
    AttemptRecord,
    CompletionResult,
    Message,
    ProviderRequest,
    ProviderResponse,
)

_DEFAULT_MAX_INFLIGHT = 32
_MESSAGE_LIMIT = 500
_KNOWN_ADAPTERS = frozenset({"gemini", "anthropic", "openai_compat"})


def _safe_hook(fn: Callable[..., None], *args: object, **kwargs: object) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        pass


def _truncate(message: str | None) -> str | None:
    if message is None:
        return None
    if len(message) <= _MESSAGE_LIMIT:
        return message
    return message[:_MESSAGE_LIMIT]


def _default_limiter(catalog: ProviderCatalog) -> InMemoryLimiter:
    per_provider = {
        entry.provider: ProviderLimit(max_inflight=_DEFAULT_MAX_INFLIGHT)
        for entry in catalog.entries
    }
    return InMemoryLimiter(per_provider=per_provider)


def _entry_for(catalog: ProviderCatalog, provider: str, model: str) -> ProviderCatalogEntry:
    for entry in catalog.entries:
        if entry.provider == provider and entry.model == model:
            return entry
    raise ConfigError(f"no catalog entry for {(provider, model)!r}")


class SmartClient:
    def __init__(
        self,
        catalog: ProviderCatalog | None = None,
        *,
        credentials: CredentialResolver | None = None,
        quota_reader: QuotaReader | None = None,
        cooldown_reader: CooldownReader | None = None,
        health_reader: HealthMetricsReader | None = None,
        lockout: ModelLockoutTracker | None = None,
        lkgp: LkgpStore | None = None,
        metrics: RollingHealthMetrics | None = None,
        limiter: Limiter | None = None,
        hooks: CompletionHooks | None = None,
        enabled_providers: frozenset[str] | None = None,
        catalog_path: str | Path | None = None,
        adapters: Mapping[tuple[str, str], ProviderAdapter] | None = None,
    ) -> None:
        path = Path(catalog_path) if catalog_path is not None else None
        self._catalog = catalog if catalog is not None else load_catalog(path=path)
        self._credentials = credentials if credentials is not None else EnvCredentialResolver()
        self._quota_reader = quota_reader
        self._cooldown_reader = cooldown_reader
        self._lockout = lockout if lockout is not None else ModelLockoutTracker()
        self._lkgp = lkgp if lkgp is not None else LkgpStore()
        self._metrics = metrics if metrics is not None else RollingHealthMetrics()
        self._health_reader = health_reader if health_reader is not None else self._metrics
        self._limiter = limiter if limiter is not None else _default_limiter(self._catalog)
        self._hooks = hooks
        self._enabled_providers = (
            enabled_providers
            if enabled_providers is not None
            else default_enabled_providers(self._catalog)
        )
        self._adapters = dict(adapters) if adapters is not None else None
        self._last_diagnostics: RoutingDiagnostics | None = None

    def explain_last_route(self) -> RoutingDiagnostics | None:
        return self._last_diagnostics

    def complete(
        self,
        *,
        prompt: str | None = None,
        messages: Sequence[Message | Mapping[str, Any]] | None = None,
        tier: str | None = None,
        task_kind: str | None = None,
        free_only: bool = False,
        freshness_required: bool = False,
        response_format: Literal["text", "json"] = "text",
        json_schema: Mapping[str, Any] | None = None,
        timeout_s: float | None = None,
        include_raw: bool = False,
        max_tokens: int | None = None,
        on_auth_failure: Literal["stop", "continue"] = "stop",
    ) -> CompletionResult:
        started = time.perf_counter()
        if json_schema is not None and response_format != "json":
            raise ValidationError("json_schema requires response_format='json'")
        if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens <= 0):
            raise ValidationError("max_tokens must be a positive integer when set")
        normalized = tuple(normalize_messages(prompt=prompt, messages=messages))
        pool = build_candidate_pool(
            self._catalog,
            credentials=self._credentials,
            tier=tier,
            free_only=free_only,
            freshness_required=freshness_required,
            enabled_providers=self._enabled_providers,
        )
        ranking = rank_candidates(
            pool,
            tier=tier,
            task_kind=task_kind,
            lockout=self._lockout,
            lkgp=self._lkgp,
            quota_reader=self._quota_reader,
            cooldown_reader=self._cooldown_reader,
            health_reader=self._health_reader,
            known_adapters=_KNOWN_ADAPTERS,
        )
        self._last_diagnostics = ranking.diagnostics
        if not ranking.ranked_targets:
            error: BaseException = NoEligibleProviders(
                "no eligible providers after ranking filters"
            )
            self._notify_failure(error, ())
            raise error

        index = {(candidate.provider, candidate.model): candidate for candidate in pool}
        attempts: list[AttemptRecord] = []
        lkgp_key = self._lkgp.make_key(tier, task_kind)
        for target in ranking.ranked_targets:
            pair = (target.provider, target.model)
            candidate = index[pair]
            reservation = None
            try:
                reservation = self._limiter.try_reserve(candidate.provider)
            except BudgetExceeded as exc:
                self._notify_failure(exc, tuple(attempts))
                raise
            except RateLimited as exc:
                self._record(
                    attempts,
                    AttemptRecord(
                        provider=candidate.provider,
                        model=candidate.model,
                        ok=False,
                        error_type="budget",
                        status_code=None,
                        latency_ms=0.0,
                        message=_truncate(str(exc)),
                    ),
                )
                continue
            request = ProviderRequest(
                messages=normalized,
                model=candidate.model,
                timeout_s=timeout_s,
                response_format=response_format,
                json_schema=json_schema,
                include_raw=include_raw,
                max_tokens=max_tokens,
            )
            call_started = time.perf_counter()
            finalized = False
            try:
                try:
                    adapter = self._adapter_for(candidate)
                    response = adapter.complete(request)
                except Exception as exc:
                    latency_ms = (time.perf_counter() - call_started) * 1000
                    self._limiter.release(reservation)
                    finalized = True
                    self._on_failure(
                        candidate,
                        exc,
                        attempts,
                        latency_ms,
                        lkgp_key,
                        on_auth_failure=on_auth_failure,
                    )
                    decision = classify_error(exc, on_auth_failure=on_auth_failure)
                    if decision.should_fallback:
                        continue
                    raise
                latency_ms = (time.perf_counter() - call_started) * 1000
                result = self._on_success(
                    candidate,
                    response,
                    reservation,
                    attempts,
                    latency_ms,
                    started,
                    tier,
                    response_format,
                    include_raw,
                    lkgp_key,
                )
                finalized = True
                if result is None:
                    continue
                if self._hooks is not None:
                    _safe_hook(self._hooks.on_success, result)
                return result
            finally:
                if not finalized:
                    self._limiter.release(reservation)

        if not attempts:
            error = NoEligibleProviders("no eligible providers after ranking filters")
        else:
            error = AllProvidersFailed("all providers failed", attempts=tuple(attempts))
        self._notify_failure(error, tuple(attempts))
        raise error

    def _adapter_for(self, candidate: Candidate) -> ProviderAdapter:
        pair = (candidate.provider, candidate.model)
        if self._adapters is not None and pair in self._adapters:
            return self._adapters[pair]
        entry = _entry_for(self._catalog, candidate.provider, candidate.model)
        return adapter_for(candidate, api_key=self._api_key(entry))

    def _api_key(self, entry: ProviderCatalogEntry) -> str:
        if entry.auth == "none":
            return ""
        name = (entry.api_key_env or "").strip()
        if isinstance(self._credentials, EnvCredentialResolver):
            return str(self._credentials._environ.get(name, "") or "")
        return os.environ.get(name, "").strip()

    def _record(self, attempts: list[AttemptRecord], record: AttemptRecord) -> None:
        attempts.append(record)
        self._metrics.record(record)
        if self._hooks is not None:
            _safe_hook(self._hooks.on_attempt, record)

    def _notify_failure(
        self, error: BaseException, attempts: tuple[AttemptRecord, ...]
    ) -> None:
        if self._hooks is not None:
            _safe_hook(self._hooks.on_failure, error, attempts=attempts)

    def _on_failure(
        self,
        candidate: Candidate,
        exc: BaseException,
        attempts: list[AttemptRecord],
        latency_ms: float,
        lkgp_key: str,
        *,
        on_auth_failure: Literal["stop", "continue"],
    ) -> None:
        self._record(
            attempts,
            AttemptRecord(
                provider=candidate.provider,
                model=candidate.model,
                ok=False,
                error_type=type(exc).__name__,
                status_code=getattr(exc, "status_code", None),
                latency_ms=latency_ms,
                message=_truncate(str(exc)),
            ),
        )
        if isinstance(exc, MultiproviderError):
            exc.attempts = tuple(attempts)
        decision = classify_error(exc, on_auth_failure=on_auth_failure)
        if decision.lock_model:
            self._lockout.lock(candidate.provider, candidate.model, decision.cooldown_s)
        remembered = self._lkgp.get(lkgp_key)
        if remembered == (candidate.provider, candidate.model):
            self._lkgp.forget(lkgp_key)
        if not decision.should_fallback:
            self._notify_failure(exc, tuple(attempts))

    def _on_success(
        self,
        candidate: Candidate,
        response: ProviderResponse,
        reservation: Any,
        attempts: list[AttemptRecord],
        latency_ms: float,
        started: float,
        tier: str | None,
        response_format: Literal["text", "json"],
        include_raw: bool,
        lkgp_key: str,
    ) -> CompletionResult | None:
        text = response.text
        if response_format == "json":
            try:
                text = extract_json_text(response.text)
            except ValidationError as exc:
                self._limiter.release(reservation)
                self._on_failure(
                    candidate,
                    exc,
                    attempts,
                    latency_ms,
                    lkgp_key,
                    on_auth_failure="stop",
                )
                return None
        self._limiter.finalize(reservation, usage=response.usage)
        self._record(
            attempts,
            AttemptRecord(
                provider=candidate.provider,
                model=candidate.model,
                ok=True,
                error_type=None,
                status_code=response.status_code,
                latency_ms=latency_ms,
                message=None,
            ),
        )
        self._lkgp.remember(lkgp_key, candidate.provider, candidate.model)
        return CompletionResult(
            text=text,
            provider=candidate.provider,
            model=candidate.model,
            tier=tier,
            latency_ms=(time.perf_counter() - started) * 1000,
            usage=response.usage,
            attempts=tuple(attempts),
            raw=response.raw if include_raw else None,
        )
