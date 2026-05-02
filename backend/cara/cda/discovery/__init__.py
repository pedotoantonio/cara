"""Per-content-type discovery modules.

Each function takes raw search hits and returns concrete `Discovery` objects
with playable URLs.
"""

from cara.cda.base import ContentType, Discovery, SearchHit
from cara.cda.discovery.article import discover_article
from cara.cda.discovery.audio_stream import discover_audio_stream
from cara.cda.discovery.document import discover_document
from cara.cda.discovery.image import discover_image
from cara.cda.discovery.podcast import discover_podcast
from cara.cda.discovery.video import discover_video


async def dispatch(content_type: ContentType, query: str, hits: list[SearchHit]) -> list[Discovery]:
    if content_type == "audio_stream":
        return await discover_audio_stream(query, hits)
    if content_type in ("article", "article_feed"):
        return await discover_article(query, hits)
    if content_type == "video":
        return await discover_video(query, hits)
    if content_type == "podcast":
        return await discover_podcast(query, hits)
    if content_type == "image":
        return await discover_image(query, hits)
    if content_type == "document":
        return await discover_document(query, hits)
    return []


__all__ = [
    "discover_article",
    "discover_audio_stream",
    "discover_document",
    "discover_image",
    "discover_podcast",
    "discover_video",
    "dispatch",
]
