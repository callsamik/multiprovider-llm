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
