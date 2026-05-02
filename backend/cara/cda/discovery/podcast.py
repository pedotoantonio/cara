"""Podcast discovery: find an RSS feed in the search hits, parse, return episodes."""

from __future__ import annotations

import asyncio

import httpx
import structlog

from cara.cda.base import Discovery, SearchHit

log = structlog.get_logger(__name__)

USER_AGENT = "CARA/0.6 (private home assistant)"


async def _fetch_text(url: str, client: httpx.AsyncClient) -> str | None:
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.text
    except Exception:  # noqa: BLE001
        return None


def _parse_feed(body: str) -> list[dict]:
    try:
        import feedparser
    except ImportError:
        return []
    parsed = feedparser.parse(body)
    out = []
    for entry in parsed.entries[:20]:
        # Take the first audio enclosure.
        audio = None
        for enc in getattr(entry, "enclosures", []) or []:
            t = (enc.get("type") or "").lower()
            if t.startswith("audio/"):
                audio = enc.get("href") or enc.get("url")
                break
        if not audio:
            continue
        out.append({
            "title": getattr(entry, "title", None),
            "url": audio,
            "published": getattr(entry, "published", None),
            "duration": getattr(entry, "itunes_duration", None),
            "summary": getattr(entry, "summary", None),
        })
    return out


async def discover_podcast(
    query: str, hits: list[SearchHit], *, max_results: int = 5
) -> list[Discovery]:
    out: list[Discovery] = []
    async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
        for hit in hits[:8]:
            if len(out) >= max_results:
                break
            body = await _fetch_text(hit.url, client)
            if not body or "<rss" not in body[:512].lower() and "<feed" not in body[:512].lower():
                continue
            episodes = await asyncio.get_running_loop().run_in_executor(None, _parse_feed, body)
            if not episodes:
                continue
            ep = episodes[0]
            out.append(
                Discovery(
                    content_type="podcast",
                    url=ep["url"],
                    title=ep.get("title") or hit.title,
                    source_domain=hit.source_domain,
                    extra={
                        "feed_url": hit.url,
                        "published": ep.get("published"),
                        "duration": ep.get("duration"),
                        "summary": ep.get("summary"),
                        "all_episodes": episodes,
                    },
                    score=0.75,
                )
            )
    return out
