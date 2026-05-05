"""CDA pipeline orchestrator.

Single entry point `discover()` runs the 7-step pipeline:
intent (caller's job) → KB lookup → search → discovery → verification →
playback (caller's job) → learning.
"""

from __future__ import annotations

import time
import uuid
from urllib.parse import urlparse

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cara.cda.base import (
    CdaError,
    CdaResult,
    ContentType,
    DiscoverRequest,
    Discovery,
)
from cara.cda.discovery import dispatch as discovery_dispatch
from cara.cda.memory import (
    deactivate_item,
    get_item,
    increment_failure,
    increment_success,
    list_active_for_query,
    list_user_kb as _list_user_kb,
    log_query,
    upsert_item,
)
from cara.cda.memory.content_kb import normalize
from cara.cda.search import build_default_chain
from cara.cda.verification import check_audio_stream, check_url
from cara.core import get_bus
from cara.models.cda import CdaContentItem

log = structlog.get_logger(__name__)


# Map content types to a search query rewriter that boosts relevance.
def _rewrite_query(content_type: ContentType, query: str) -> str:
    q = query.strip()
    if content_type == "audio_stream":
        return f"{q} streaming audio live"
    if content_type in ("article", "article_feed"):
        return q
    if content_type == "video":
        return f"{q} video"
    if content_type == "podcast":
        return f"{q} podcast rss feed"
    if content_type == "image":
        return q
    if content_type == "document":
        return f"{q} pdf"
    return q


def _domain_of(url: str) -> str | None:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


async def _verify(disc: Discovery) -> bool:
    if disc.content_type == "audio_stream":
        r = await check_audio_stream(disc.url)
        return r.ok
    # For everything else, a HEAD/GET check is enough.
    r = await check_url(disc.url)
    return r.ok


def _result_from_item(item: CdaContentItem, *, started_at: float, cached: bool) -> CdaResult:
    return CdaResult(
        kind=item.content_type,  # type: ignore[arg-type]
        url=item.url,
        title=item.title,
        source_domain=item.source_domain,
        metadata=item.metadata_ or {},
        confidence=float(item.confidence_score),
        cached=cached,
        duration_ms_to_resolve=int((time.perf_counter() - started_at) * 1000),
        content_id=item.id,
        fallbacks=[],
    )


async def discover(session: AsyncSession, req: DiscoverRequest) -> CdaResult:
    """Run the pipeline; return one playable result.

    Raises `CdaError` if no candidate verifies — the caller decides how to
    surface the failure (log + chat reply).
    """
    started = time.perf_counter()
    nq = normalize(req.raw_query)
    bus = get_bus()
    bus.emit(
        "cda.discovery.start",
        {
            "user_id": req.user_id,
            "query": req.raw_query[:80],
            "content_type": req.content_type,
        },
    )

    # 2. KB lookup -------------------------------------------------------
    kb_hits = await list_active_for_query(
        session, query=nq, content_type=req.content_type, limit=3
    )
    if kb_hits:
        # Try the top KB candidate; if it fails verification, fall through
        # to fresh search (and mark failure).
        for cand in kb_hits:
            if cand.content_type == "article_feed":
                # Don't return a feed URL to the player; we'll go through
                # discovery below to fetch latest items from the feed.
                continue
            disc = Discovery(
                content_type=cand.content_type,  # type: ignore[arg-type]
                url=cand.url,
                title=cand.title,
                source_domain=cand.source_domain,
                extra=cand.metadata_ or {},
                score=float(cand.confidence_score),
            )
            ok = await _verify(disc)
            if ok:
                await increment_success(session, cand.id)
                await log_query(
                    session,
                    user_id=req.user_id,
                    raw_query=req.raw_query,
                    normalized_query=nq,
                    intent={"content_type": req.content_type, "modifiers": req.modifiers},
                    resolved_content_id=cand.id,
                    outcome="success",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    cached=True,
                )
                bus.emit(
                    "cda.discovery.cached_hit",
                    {
                        "user_id": req.user_id,
                        "content_type": cand.content_type,
                        "url": cand.url,
                        "domain": cand.source_domain,
                    },
                )
                return _result_from_item(cand, started_at=started, cached=True)
            else:
                await increment_failure(session, cand.id)
                if cand.failure_count + 1 - cand.success_count >= 3:
                    await deactivate_item(session, cand.id)
                # try the next kb hit; if all fail, fall through to fresh search
                log.info("cda.kb.cand.unverified", item_id=str(cand.id), url=cand.url)

    # 3. Web search ------------------------------------------------------
    chain = build_default_chain()
    rewritten = _rewrite_query(req.content_type, req.raw_query)
    hits = await chain.search(rewritten, limit=10)
    if not hits:
        await log_query(
            session,
            user_id=req.user_id,
            raw_query=req.raw_query,
            normalized_query=nq,
            intent={"content_type": req.content_type, "modifiers": req.modifiers},
            resolved_content_id=None,
            outcome="no_results",
            duration_ms=int((time.perf_counter() - started) * 1000),
            cached=False,
        )
        bus.emit(
            "cda.discovery.failed",
            {
                "user_id": req.user_id,
                "query": req.raw_query[:80],
                "content_type": req.content_type,
                "outcome": "no_results",
            },
        )
        raise CdaError("Non ho trovato nulla per questa richiesta.")

    # 4. Discovery -------------------------------------------------------
    candidates = await discovery_dispatch(req.content_type, req.raw_query, hits)
    if not candidates:
        await log_query(
            session,
            user_id=req.user_id,
            raw_query=req.raw_query,
            normalized_query=nq,
            intent={"content_type": req.content_type, "modifiers": req.modifiers},
            resolved_content_id=None,
            outcome="no_candidates",
            duration_ms=int((time.perf_counter() - started) * 1000),
            cached=False,
        )
        raise CdaError("Ho trovato risultati ma non riesco a estrarre qualcosa di riproducibile.")

    # 5. Verification ----------------------------------------------------
    candidates.sort(key=lambda d: -d.score)
    chosen: Discovery | None = None
    for d in candidates[:5]:
        if await _verify(d):
            chosen = d
            break

    if chosen is None:
        await log_query(
            session,
            user_id=req.user_id,
            raw_query=req.raw_query,
            normalized_query=nq,
            intent={"content_type": req.content_type, "modifiers": req.modifiers},
            resolved_content_id=None,
            outcome="verification_failed",
            duration_ms=int((time.perf_counter() - started) * 1000),
            cached=False,
        )
        raise CdaError("Ho trovato candidati ma nessuno è raggiungibile in questo momento.")

    # 7. Persist + log ---------------------------------------------------
    item = await upsert_item(
        session,
        query_normalized=nq,
        content_type=chosen.content_type,
        url=chosen.url,
        title=chosen.title,
        source_domain=chosen.source_domain or _domain_of(chosen.url),
        metadata=chosen.extra or {},
        discovered_via="search",
        discovered_by_user_id=req.user_id,
    )
    await increment_success(session, item.id)
    await log_query(
        session,
        user_id=req.user_id,
        raw_query=req.raw_query,
        normalized_query=nq,
        intent={"content_type": req.content_type, "modifiers": req.modifiers},
        resolved_content_id=item.id,
        outcome="success",
        duration_ms=int((time.perf_counter() - started) * 1000),
        cached=False,
    )

    fallbacks = [d for d in candidates if d.url != chosen.url][:3]
    res = _result_from_item(item, started_at=started, cached=False)
    res.fallbacks = fallbacks
    bus.emit(
        "cda.discovery.success",
        {
            "user_id": req.user_id,
            "content_type": chosen.content_type,
            "url": chosen.url,
            "domain": chosen.source_domain,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return res


# ---- public helpers (used by REST endpoints) ----------------------------


async def list_user_kb(
    session: AsyncSession, *, user_id: int | None,
    content_type: ContentType | None = None, limit: int = 50,
    only_active: bool = True,
) -> list[CdaContentItem]:
    return await _list_user_kb(
        session, user_id=user_id, content_type=content_type, limit=limit,
        only_active=only_active,
    )


async def set_item_active(
    session: AsyncSession, item_id: uuid.UUID, *, is_active: bool
) -> CdaContentItem | None:
    """Admin: toggle is_active. Returns None if the item doesn't exist."""
    item = await get_item(session, item_id)
    if item is None:
        return None
    item.is_active = is_active
    await session.flush()
    return item


async def record_feedback_started(session: AsyncSession, content_id: uuid.UUID) -> None:
    item = await get_item(session, content_id)
    if item is None:
        return
    log.info("cda.feedback.started", content_id=str(content_id))


async def record_feedback_stopped(
    session: AsyncSession, *, content_id: uuid.UUID, played_seconds: float, reason: str
) -> None:
    item = await get_item(session, content_id)
    if item is None:
        return
    if reason == "error" or (reason == "user_stop" and played_seconds < 2):
        await increment_failure(session, item.id)
        if item.failure_count + 1 - item.success_count >= 3:
            await deactivate_item(session, item.id)
    elif played_seconds >= 5:
        await increment_success(session, item.id)
    log.info(
        "cda.feedback.stopped",
        content_id=str(content_id),
        played_seconds=played_seconds,
        reason=reason,
    )


async def record_feedback_regenerated(session: AsyncSession, content_id: uuid.UUID) -> None:
    item = await get_item(session, content_id)
    if item is None:
        return
    await increment_failure(session, item.id)
    log.info("cda.feedback.regenerated", content_id=str(content_id))
