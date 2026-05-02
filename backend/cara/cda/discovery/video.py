"""Video discovery — YouTube embed default; yt-dlp fallback for other domains."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import structlog

from cara.cda.base import Discovery, SearchHit

log = structlog.get_logger(__name__)


_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def _youtube_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
    except Exception:  # noqa: BLE001
        return None
    if host not in _YT_HOSTS:
        return None
    if host == "youtu.be":
        return parsed.path.lstrip("/").split("/", 1)[0] or None
    if parsed.path == "/watch":
        return parse_qs(parsed.query).get("v", [None])[0]
    m = re.match(r"^/embed/([a-zA-Z0-9_-]{6,})", parsed.path)
    if m:
        return m.group(1)
    m = re.match(r"^/shorts/([a-zA-Z0-9_-]{6,})", parsed.path)
    if m:
        return m.group(1)
    return None


async def discover_video(
    query: str, hits: list[SearchHit], *, max_results: int = 5
) -> list[Discovery]:
    out: list[Discovery] = []
    seen_ids: set[str] = set()
    for hit in hits:
        if len(out) >= max_results:
            break
        vid = _youtube_video_id(hit.url)
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            out.append(
                Discovery(
                    content_type="video",
                    url=f"https://www.youtube.com/embed/{vid}",
                    title=hit.title,
                    source_domain="youtube.com",
                    extra={
                        "youtube_id": vid,
                        "embed": True,
                        "original_url": hit.url,
                    },
                    score=0.85,
                )
            )
            continue
        # Direct video files (.mp4 / .webm) on other domains.
        low = hit.url.lower().split("?", 1)[0]
        if low.endswith((".mp4", ".webm", ".m3u8")):
            out.append(
                Discovery(
                    content_type="video",
                    url=hit.url,
                    title=hit.title,
                    source_domain=hit.source_domain,
                    extra={"embed": False, "original_url": hit.url},
                    score=0.7,
                )
            )
    return out
