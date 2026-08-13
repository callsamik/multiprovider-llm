"""multiprovider-llm — multi-provider LLM client (see docs/design.md)."""

from __future__ import annotations

from .async_client import AsyncClient
from .client import Client
from .config import config_from_dict, load_config
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
    "AsyncClient",
    "BudgetExceeded",
    "Client",
    "CompletionResult",
    "ConfigError",
    "config_from_dict",
    "load_config",
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
