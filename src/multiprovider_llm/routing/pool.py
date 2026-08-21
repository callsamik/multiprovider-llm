from __future__ import annotations

from ..catalog.credentials import CredentialResolver
from ..catalog.provider_catalog import ProviderCatalog
from .types import Candidate


def default_enabled_providers(catalog: ProviderCatalog) -> frozenset[str]:
    return frozenset(e.provider for e in catalog.entries if e.enabled_by_default)


def build_candidate_pool(
    catalog: ProviderCatalog,
    *,
    credentials: CredentialResolver,
    tier: str | None,
    free_only: bool,
    freshness_required: bool,
    enabled_providers: frozenset[str] | None = None,
) -> tuple[Candidate, ...]:
    del tier  # accepted for a stable call shape; membership is not tier-ranked here
    seen: set[tuple[str, str]] = set()
    out: list[Candidate] = []
    for entry in catalog.entries:
        pair = (entry.provider, entry.model)
        if pair in seen:
            continue
        if not credentials.has_key(entry):
            continue
        if free_only and entry.cost_tier == "paid":
            continue
        if freshness_required and not entry.freshness_ok:
            continue
        if enabled_providers is not None and entry.provider not in enabled_providers:
            continue
        seen.add(pair)
        out.append(
            Candidate(
                provider=entry.provider,
                model=entry.model,
                adapter=entry.adapter,
                base_url=entry.base_url,
                cost_tier=entry.cost_tier,
                freshness_ok=entry.freshness_ok,
                tier_affinity=entry.tier_affinity,
                http_referer=entry.http_referer,
            )
        )
    return tuple(out)
