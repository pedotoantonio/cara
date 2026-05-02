"""Image discovery: filter hits whose URL or content-type is an image."""

from __future__ import annotations

import re

from cara.cda.base import Discovery, SearchHit

_IMG_EXT_RE = re.compile(r"\.(jpe?g|png|gif|webp|bmp|svg)(?:\?|$)", re.IGNORECASE)


async def discover_image(
    query: str, hits: list[SearchHit], *, max_results: int = 8
) -> list[Discovery]:
    out: list[Discovery] = []
    for hit in hits:
        if _IMG_EXT_RE.search(hit.url):
            out.append(
                Discovery(
                    content_type="image",
                    url=hit.url,
                    title=hit.title,
                    source_domain=hit.source_domain,
                    extra={"snippet": hit.snippet},
                    score=0.7,
                )
            )
            if len(out) >= max_results:
                break
    return out
