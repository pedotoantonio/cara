"""SearXNG provider — self-hosted meta-search.

Container is expected to live on the proxy-net (e.g. cara-searxng:8080).
Returns top-N JSON results.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import structlog

from cara.cda.base import SearchHit
from cara.cda.search.base import SearchProvider, SearchProviderError

log = structlog.get_logger(__name__)


class SearXNGProvider(SearchProvider):
    name = "searxng"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        url = f"{self.base_url}/search"
        params = {"q": query, "format": "json", "safesearch": 1}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.info("cda.searxng.failed", error=str(exc))
            raise SearchProviderError(f"searxng: {exc}") from exc

        hits: list[SearchHit] = []
        for i, raw in enumerate(data.get("results", [])[:limit]):
            link = raw.get("url")
            if not link:
                continue
            hits.append(
                SearchHit(
                    url=link,
                    title=raw.get("title"),
                    snippet=raw.get("content"),
                    source_domain=urlparse(link).netloc.lower().lstrip("www."),
                    rank=i,
                )
            )
        return hits
