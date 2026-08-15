from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import AttemptRecord, CompletionResult, ProviderRequest, ProviderResponse, Usage


@runtime_checkable
class CompletionHooks(Protocol):
    def on_attempt(self, record: AttemptRecord) -> None: ...

    def on_success(self, result: CompletionResult) -> None: ...

    def on_failure(
        self, error: BaseException, *, attempts: tuple[AttemptRecord, ...]
    ) -> None: ...


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
