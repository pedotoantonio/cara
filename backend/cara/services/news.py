"""News aggregator: pulls public RSS feeds, normalises, caches in-memory.

No third-party search API, no tracking. Each fetch goes out with a neutral
user-agent. Refresh is opportunistic (cache TTL 10 min) so the first request
of the day is the slow one.

Filter by `category` ("italia", "mondo", "tech", "sport", "all"). When a
feed is unreachable it is silently skipped — degraded but not broken.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import feedparser
import httpx
import structlog

logger = structlog.get_logger(__name__)

USER_AGENT = "CARA/0.1 (private home assistant; +internal)"

# Map of source-id → (display_name, url, categories)
FEEDS: dict[str, tuple[str, str, list[str]]] = {
    "ansa_top":          ("ANSA — Top",          "https://www.ansa.it/sito/ansait_rss.xml", ["italia", "all"]),
    "ansa_mondo":        ("ANSA — Mondo",        "https://www.ansa.it/sito/notizie/mondo/mondo_rss.xml", ["mondo", "all"]),
    "ansa_economia":     ("ANSA — Economia",     "https://www.ansa.it/sito/notizie/economia/economia_rss.xml", ["economia", "all"]),
    "ansa_tecnologia":   ("ANSA — Tecnologia",   "https://www.ansa.it/sito/notizie/tecnologia/tecnologia_rss.xml", ["tech", "all"]),
    "ansa_sport":        ("ANSA — Sport",        "https://www.ansa.it/sito/notizie/sport/sport_rss.xml", ["sport", "all"]),
    "repubblica_home":   ("Repubblica",          "https://www.repubblica.it/rss/homepage/rss2.0.xml", ["italia", "all"]),
    "corriere_home":     ("Corriere della Sera", "https://xml2.corriereobjects.it/rss/homepage.xml", ["italia", "all"]),
    "ilsole24_home":     ("Il Sole 24 Ore",      "https://www.ilsole24ore.com/rss/notizie.xml", ["italia", "economia", "all"]),
    "rainews_home":      ("RAI News",            "https://www.rainews.it/rss/home", ["italia", "all"]),
    "bbc_world":         ("BBC — World",         "http://feeds.bbci.co.uk/news/world/rss.xml", ["mondo", "all"]),
    "reuters_world":     ("Reuters — World",     "https://www.reutersagency.com/feed/?best-topics=international&post_type=best", ["mondo", "all"]),
}

CATEGORIES = ["all", "italia", "mondo", "economia", "tech", "sport"]
CACHE_TTL_SECONDS = 600   # 10 minutes
HTTP_TIMEOUT = 6.0


@dataclass(slots=True)
class NewsItem:
    title: str
    summary: str
    link: str
    source: str
    published: str | None  # ISO


# In-process cache (per worker). Keys are source-id.
_cache: dict[str, tuple[float, list[NewsItem]]] = {}
_cache_lock = asyncio.Lock()


def _parse_entry(entry: Any, source: str) -> NewsItem:
    title = getattr(entry, "title", "") or ""
    summary = getattr(entry, "summary", "") or ""
    # feedparser populates `published` or `updated` depending on the feed.
    published_iso: str | None = None
    if getattr(entry, "published_parsed", None):
        published_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", entry.published_parsed)
    elif getattr(entry, "updated_parsed", None):
        published_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", entry.updated_parsed)
    return NewsItem(
        title=title.strip()[:300],
        summary=_strip_html(summary).strip()[:600],
        link=getattr(entry, "link", "") or "",
        source=source,
        published=published_iso,
    )


def _strip_html(text: str) -> str:
    # super lightweight — most RSS summaries embed simple <p>/<br/>
    out: list[str] = []
    in_tag = False
    for ch in text:
        if ch == "<":
            in_tag = True
            continue
        if ch == ">":
            in_tag = False
            continue
        if not in_tag:
            out.append(ch)
    return "".join(out)


async def _fetch_one(source_id: str, name: str, url: str) -> list[NewsItem]:
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True,
                                      headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url)
            r.raise_for_status()
            text = r.text
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("news.fetch_failed", source=source_id, error=str(exc))
        return []
    # feedparser is sync but cheap; run in default executor to avoid blocking.
    parsed = await asyncio.to_thread(feedparser.parse, text)
    items = [_parse_entry(e, name) for e in parsed.entries[:30]]
    return items


_ITALIAN_ORDINALS = [
    "primo", "secondo", "terzo", "quarto", "quinto",
    "sesto", "settimo", "ottavo", "nono", "decimo",
]


def make_digest(items: list[NewsItem], *, category: str) -> str:
    """Compose an Italian, TTS-friendly digest of the top items.

    The titles are written by professional newsrooms — we just glue them
    together with Italian ordinals so the speech engine can read them as
    distinct sentences.
    """
    if not items:
        return f"Non ho trovato notizie nella categoria {category}."
    headline = {
        "all": "le ultime notizie",
        "italia": "le ultime notizie dall'Italia",
        "mondo": "le ultime notizie dal mondo",
        "economia": "le ultime notizie di economia",
        "tech": "le ultime notizie di tecnologia",
        "sport": "le ultime notizie di sport",
    }.get(category, "le ultime notizie")
    take = items[: min(5, len(items))]
    parts: list[str] = [f"Ecco {headline}."]
    for i, it in enumerate(take):
        ord_word = _ITALIAN_ORDINALS[i] if i < len(_ITALIAN_ORDINALS) else f"numero {i + 1}"
        title = (it.title or "").rstrip(" .;:")
        parts.append(f"{ord_word.capitalize()}: {title}, da {it.source}.")
    return " ".join(parts)


async def fetch_category(category: str = "all", *, limit: int = 20) -> list[NewsItem]:
    if category not in CATEGORIES:
        category = "all"
    selected = [(sid, name, url) for sid, (name, url, cats) in FEEDS.items() if category in cats]
    now = time.monotonic()
    out: list[NewsItem] = []

    async def _src(sid: str, name: str, url: str) -> list[NewsItem]:
        async with _cache_lock:
            cached = _cache.get(sid)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        items = await _fetch_one(sid, name, url)
        async with _cache_lock:
            _cache[sid] = (now, items)
        return items

    results = await asyncio.gather(*(_src(sid, name, url) for sid, name, url in selected))
    for r in results:
        out.extend(r)
    # Sort by published desc when present, fall back to original order.
    out.sort(key=lambda x: x.published or "", reverse=True)
    return out[:limit]
