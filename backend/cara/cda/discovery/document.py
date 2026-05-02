"""Document discovery: filter hits whose URL points to a downloadable document."""

from __future__ import annotations

import re

from cara.cda.base import Discovery, SearchHit

_DOC_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|odt|rtf|txt)(?:\?|$)", re.IGNORECASE)


async def discover_document(
    query: str, hits: list[SearchHit], *, max_results: int = 5
) -> list[Discovery]:
    out: list[Discovery] = []
    for hit in hits:
        m = _DOC_EXT_RE.search(hit.url)
        if not m:
            continue
        ext = m.group(1).lower()
        out.append(
            Discovery(
                content_type="document",
                url=hit.url,
                title=hit.title,
                source_domain=hit.source_domain,
                extra={"extension": ext, "snippet": hit.snippet},
                score=0.7,
            )
        )
        if len(out) >= max_results:
            break
    return out
