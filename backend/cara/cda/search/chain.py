"""Provider chain: try in order, first that returns >0 hits wins."""

from __future__ import annotations

import structlog

from cara.cda.base import SearchHit
from cara.cda.search.base import SearchProvider, SearchProviderError
from cara.cda.search.ddg import DDGProvider
from cara.cda.search.searxng import SearXNGProvider
from cara.config import settings

log = structlog.get_logger(__name__)


class ProviderChain:
    def __init__(self, providers: list[SearchProvider]):
        self.providers = providers

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        for p in self.providers:
            try:
                hits = await p.search(query, limit=limit)
                if hits:
                    log.info("cda.search.ok", provider=p.name, query=query, hits=len(hits))
                    return hits
            except SearchProviderError as exc:
                log.info("cda.search.skip", provider=p.name, error=str(exc))
                continue
        log.info("cda.search.empty", query=query)
        return []


def build_default_chain() -> ProviderChain:
    """Build the default chain from current settings.

    SearXNG (if reachable URL is set in env CDA_SEARXNG_URL) → DDG.
    """
    providers: list[SearchProvider] = []
    sx_url = getattr(settings, "cda_searxng_url", "") or ""
    if sx_url:
        providers.append(SearXNGProvider(sx_url))
    providers.append(DDGProvider())
    return ProviderChain(providers)
