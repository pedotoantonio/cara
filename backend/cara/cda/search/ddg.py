"""DuckDuckGo HTML scraper — minimal, no API key.

Used as a last-resort fallback when SearXNG is unreachable. Parsing is fragile
by design (DDG can change the HTML); we tolerate failure and return an empty
list rather than raising — the orchestrator then falls back to "no results".
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import structlog

from cara.cda.base import SearchHit
from cara.cda.search.base import SearchProvider, SearchProviderError

log = structlog.get_logger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; CARA/0.6 search)"


class DDGProvider(SearchProvider):
    name = "ddg"

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=8.0,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                r = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query, "kl": "wt-wt"},
                )
                r.raise_for_status()
                html = r.text
        except Exception as exc:  # noqa: BLE001
            log.info("cda.ddg.failed", error=str(exc))
            raise SearchProviderError(f"ddg: {exc}") from exc

        # Cheap HTML extraction; DDG's HTML version uses a specific structure.
        # We extract <a class="result__a" href="..."> and the snippet that
        # follows in <a class="result__snippet">.
        hits: list[SearchHit] = []
        href_re = re.compile(
            r'<a\s+[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        snippet_re = re.compile(
            r'<a\s+[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        snippets = [_strip_tags(unescape(m.group(1))) for m in snippet_re.finditer(html)]
        for i, m in enumerate(href_re.finditer(html)):
            if len(hits) >= limit:
                break
            raw_url = unescape(m.group(1))
            real = _unwrap_ddg(raw_url)
            if not real:
                continue
            title = _strip_tags(unescape(m.group(2)))
            hits.append(
                SearchHit(
                    url=real,
                    title=title or None,
                    snippet=snippets[i] if i < len(snippets) else None,
                    source_domain=urlparse(real).netloc.lower().lstrip("www."),
                    rank=i,
                )
            )
        return hits


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _unwrap_ddg(href: str) -> str | None:
    """DDG HTML returns links as `/l/?uddg=<url-encoded-target>`. Unwrap."""
    if href.startswith("//duckduckgo.com/l/"):
        href = "https:" + href
    if href.startswith("/l/") or "duckduckgo.com/l/" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            target = qs.get("uddg", [None])[0]
            if target:
                return unquote(target)
        except Exception:  # noqa: BLE001
            return None
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return None
