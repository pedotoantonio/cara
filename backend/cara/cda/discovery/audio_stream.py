"""Audio stream discovery.

Given a list of web-search hits, find playable stream URLs by:
1. Filtering hits whose URL itself is an obvious stream (.m3u, .m3u8, .pls, .mp3, .aac).
2. Fetching candidate pages and extracting embedded stream URLs (regex on HTML).
3. For .m3u / .pls playlists, parsing them to extract the first valid stream entry.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
import structlog

from cara.cda.base import Discovery, SearchHit

log = structlog.get_logger(__name__)

USER_AGENT = "CARA/0.6 (private home assistant)"

# Patterns recognised as audio stream URLs in HTML/JS.
_STREAM_URL_RE = re.compile(
    r'(?P<url>https?://[^\s"\'<>]+\.(?:m3u8|m3u|pls|mp3|aac|ogg)(?:\?[^\s"\'<>]*)?)',
    re.IGNORECASE,
)
# Some sites embed shoutcast/icecast endpoints with no extension.
_ICECAST_URL_RE = re.compile(
    r'(?P<url>https?://[^\s"\'<>]+(?:icecast|shoutcast|stream|live)[^\s"\'<>]*)',
    re.IGNORECASE,
)


def _is_stream_url(url: str) -> bool:
    low = url.lower().split("?", 1)[0]
    return low.endswith((".m3u", ".m3u8", ".pls", ".mp3", ".aac", ".ogg"))


async def _fetch_page(url: str, client: httpx.AsyncClient) -> str | None:
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.text
    except Exception as exc:  # noqa: BLE001
        log.debug("cda.audio.fetch.failed", url=url, error=str(exc))
        return None


async def _resolve_pls_or_m3u(url: str, client: httpx.AsyncClient) -> str | None:
    """Open a .pls / .m3u and return the first http(s) entry inside."""
    body = await _fetch_page(url, client)
    if not body:
        return None
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("file") and "=" in line:  # File1=http://…
            line = line.split("=", 1)[1].strip()
        if line.startswith("http://") or line.startswith("https://"):
            return line
    return None


async def discover_audio_stream(
    query: str, hits: list[SearchHit], *, max_candidates: int = 8
) -> list[Discovery]:
    out: list[Discovery] = []
    seen: set[str] = set()

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=6.0,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for hit in hits[:max_candidates]:
            # Direct stream URL in the search result.
            if _is_stream_url(hit.url):
                resolved = hit.url
                if hit.url.lower().endswith((".m3u", ".pls")):
                    inner = await _resolve_pls_or_m3u(hit.url, client)
                    resolved = inner or hit.url
                if resolved in seen:
                    continue
                seen.add(resolved)
                out.append(
                    Discovery(
                        content_type="audio_stream",
                        url=resolved,
                        title=hit.title,
                        source_domain=hit.source_domain,
                        extra={"discovered_from": hit.url},
                        score=0.9,
                    )
                )
                continue

            # Otherwise, try to find one inside the page HTML.
            html = await _fetch_page(hit.url, client)
            if not html:
                continue
            for match_re, base_score in ((_STREAM_URL_RE, 0.75), (_ICECAST_URL_RE, 0.55)):
                for m in match_re.finditer(html):
                    candidate = m.group("url")
                    # Resolve relative URLs (regex catches absolute by design,
                    # but be defensive).
                    if not candidate.startswith(("http://", "https://")):
                        candidate = urljoin(hit.url, candidate)
                    if candidate in seen:
                        continue
                    seen.add(candidate)
                    if candidate.lower().endswith((".m3u", ".pls")):
                        inner = await _resolve_pls_or_m3u(candidate, client)
                        if inner:
                            candidate = inner
                    out.append(
                        Discovery(
                            content_type="audio_stream",
                            url=candidate,
                            title=hit.title,
                            source_domain=hit.source_domain
                                          or urlparse(candidate).netloc.lower(),
                            extra={"discovered_from": hit.url},
                            score=base_score,
                        )
                    )
                    if len(out) >= max_candidates:
                        return out
    return out
