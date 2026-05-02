"""Article discovery: fetch top hits, extract clean text.

Uses `trafilatura` (preferred) with a regex-based fallback if the package or
the extraction fails. Returns Discovery objects with the original URL plus
extracted text in `extra["text"]`.
"""

from __future__ import annotations

import re
from html import unescape

import httpx
import structlog

from cara.cda.base import Discovery, SearchHit

log = structlog.get_logger(__name__)

USER_AGENT = "CARA/0.6 (private home assistant)"


async def _fetch_html(url: str, client: httpx.AsyncClient) -> str | None:
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.text
    except Exception as exc:  # noqa: BLE001
        log.debug("cda.article.fetch.failed", url=url, error=str(exc))
        return None


def _extract_with_trafilatura(html: str, url: str) -> dict | None:
    try:
        import trafilatura  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        meta = trafilatura.metadata.extract_metadata(html, default_url=url)
        text = trafilatura.extract(
            html, include_comments=False, include_tables=False, no_fallback=False
        )
        if not text or len(text) < 200:
            return None
        return {
            "title": (meta.title if meta else None),
            "author": (meta.author if meta else None),
            "date": (meta.date if meta else None),
            "text": text.strip(),
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("cda.article.trafilatura.failed", url=url, error=str(exc))
        return None


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _extract_with_regex(html: str) -> dict | None:
    cleaned = _SCRIPT_RE.sub("", html)
    cleaned = _STYLE_RE.sub("", cleaned)
    text = _TAG_RE.sub(" ", cleaned)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 200:
        return None
    title_m = _TITLE_RE.search(html)
    return {
        "title": (title_m.group(1).strip() if title_m else None),
        "author": None,
        "date": None,
        "text": text[:8000],   # cap large pages
    }


async def discover_article(
    query: str, hits: list[SearchHit], *, max_results: int = 5
) -> list[Discovery]:
    out: list[Discovery] = []
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=8.0,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for hit in hits[: max_results * 2]:
            html = await _fetch_html(hit.url, client)
            if not html:
                continue
            extracted = _extract_with_trafilatura(html, hit.url) or _extract_with_regex(html)
            if not extracted:
                continue
            out.append(
                Discovery(
                    content_type="article",
                    url=hit.url,
                    title=extracted.get("title") or hit.title,
                    source_domain=hit.source_domain,
                    extra={
                        "text": extracted["text"],
                        "author": extracted.get("author"),
                        "date": extracted.get("date"),
                        "snippet": hit.snippet,
                    },
                    score=0.7,
                )
            )
            if len(out) >= max_results:
                break
    return out
