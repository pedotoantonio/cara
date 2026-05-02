"""Shared types for the Content Discovery Agent."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


# Closed set of content kinds the system can discover and play.
ContentType = Literal[
    "audio_stream",   # radio (icecast/shoutcast/m3u/m3u8/pls/direct mp3)
    "article",        # text article (extracted with trafilatura)
    "article_feed",   # an RSS feed (used as a starting point for `article`)
    "video",          # YouTube embed or direct video file
    "podcast",        # an episode (mp3) of an RSS-feed podcast
    "image",          # static image
    "document",       # PDF / DOCX / etc
]


class CdaError(Exception):
    """Pipeline-level errors that should be surfaced to the user."""


@dataclass
class DiscoverRequest:
    user_id: int
    raw_query: str
    content_type: ContentType
    modifiers: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchHit:
    """One web-search result, before per-type discovery."""

    url: str
    title: str | None = None
    snippet: str | None = None
    source_domain: str | None = None
    rank: int = 0


@dataclass
class Discovery:
    """One concrete piece of content the user can play.

    `extra` may carry per-type metadata (e.g. bitrate, codec, video_id, feed_url).
    """

    content_type: ContentType
    url: str
    title: str | None = None
    source_domain: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    score: float = 0.5  # 0..1, used to rank candidates


@dataclass
class CdaResult:
    """Final answer to the orchestrator caller."""

    kind: ContentType
    url: str
    title: str | None
    source_domain: str | None
    metadata: dict[str, Any]
    confidence: float
    cached: bool
    duration_ms_to_resolve: int
    content_id: uuid.UUID
    fallbacks: list[Discovery] = field(default_factory=list)
