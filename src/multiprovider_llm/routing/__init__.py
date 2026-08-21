from importlib import import_module

from .chain import is_auth_failure, is_retryable, resolve_chain, resolve_model

__all__ = [
    "Candidate",
    "RankedTarget",
    "RankingResult",
    "RoutingDiagnostics",
    "build_candidate_pool",
    "default_enabled_providers",
    "is_auth_failure",
    "is_retryable",
    "rank_candidates",
    "resolve_chain",
    "resolve_model",
]

_LAZY = {
    "Candidate": ".types",
    "RankedTarget": ".types",
    "RankingResult": ".types",
    "RoutingDiagnostics": ".types",
    "build_candidate_pool": ".pool",
    "default_enabled_providers": ".pool",
    "rank_candidates": ".rank",
}


def __getattr__(name: str):
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __package__), name)
    globals()[name] = value
    return value
