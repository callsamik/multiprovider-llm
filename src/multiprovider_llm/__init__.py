"""multiprovider-llm — multi-provider LLM client (see docs/design.md)."""

from __future__ import annotations

from .client import Client
from .errors import (
    AllProvidersFailed,
    BudgetExceeded,
    ConfigError,
    MultiproviderError,
    NoEligibleProviders,
    ProviderError,
    RateLimited,
    ValidationError,
)
from .types import AttemptRecord, CompletionResult, Message, Usage

__all__ = [
    "AllProvidersFailed",
    "AttemptRecord",
    "BudgetExceeded",
    "Client",
    "CompletionResult",
    "ConfigError",
    "Message",
    "MultiproviderError",
    "NoEligibleProviders",
    "ProviderError",
    "RateLimited",
    "Usage",
    "ValidationError",
    "__version__",
]
__version__ = "0.1.0a1"
