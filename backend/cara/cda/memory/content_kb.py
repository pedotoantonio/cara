"""CRUD over `cda_content_items` and `cda_query_log`."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cara.cda.base import ContentType
from cara.models.cda import CdaContentItem, CdaQueryLog


def normalize(query: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation that is rarely meaningful."""
    s = query.strip().lower()
    # Strip trailing punctuation
    while s and s[-1] in "?!.,;:":
        s = s[:-1]
    # Collapse spaces
    return " ".join(s.split())


async def list_active_for_query(
    session: AsyncSession,
    *,
    query: str,
    content_type: ContentType | None = None,
    limit: int = 5,
) -> list[CdaContentItem]:
    """Return active items whose normalized query matches or substring-matches."""
    nq = normalize(query)
    stmt = select(CdaContentItem).where(CdaContentItem.is_active.is_(True))
    if content_type is not None:
        stmt = stmt.where(CdaContentItem.content_type == content_type)
    # Two-pass: exact match first, then substring fallback. We do it in Python
    # to keep ranking deterministic and easy to reason about.
    rows = (await session.execute(stmt)).scalars().all()
    exact = [r for r in rows if r.query_normalized == nq]
    if exact:
        exact.sort(key=lambda r: (-r.confidence_score, -r.success_count))
        return exact[:limit]
    sub = [r for r in rows if nq and (nq in r.query_normalized or r.query_normalized in nq)]
    sub.sort(key=lambda r: (-r.confidence_score, -r.success_count))
    return sub[:limit]


async def list_user_kb(
    session: AsyncSession,
    *,
    user_id: int | None,
    content_type: ContentType | None = None,
    limit: int = 50,
    only_active: bool = True,
) -> list[CdaContentItem]:
    """List items the user has discovered (plus seeds visible to all)."""
    stmt = select(CdaContentItem)
    if only_active:
        stmt = stmt.where(CdaContentItem.is_active.is_(True))
    if content_type is not None:
        stmt = stmt.where(CdaContentItem.content_type == content_type)
    if user_id is not None:
        stmt = stmt.where(
            (CdaContentItem.discovered_by_user_id == user_id)
            | (CdaContentItem.discovered_by_user_id.is_(None))
        )
    stmt = stmt.order_by(desc(CdaContentItem.success_count), desc(CdaContentItem.confidence_score))
    stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_item(session: AsyncSession, item_id: uuid.UUID) -> CdaContentItem | None:
    return await session.get(CdaContentItem, item_id)


async def upsert_item(
    session: AsyncSession,
    *,
    query_normalized: str,
    content_type: ContentType,
    url: str,
    title: str | None,
    source_domain: str | None,
    metadata: dict[str, Any],
    discovered_via: str,
    discovered_by_user_id: int | None,
) -> CdaContentItem:
    """Insert or update an item. Returns the persisted row."""
    stmt = select(CdaContentItem).where(
        CdaContentItem.query_normalized == query_normalized,
        CdaContentItem.url == url,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        existing.title = title or existing.title
        existing.source_domain = source_domain or existing.source_domain
        existing.metadata_ = {**(existing.metadata_ or {}), **(metadata or {})}
        existing.is_active = True
        await session.flush()
        return existing
    row = CdaContentItem(
        query_normalized=query_normalized,
        content_type=content_type,
        url=url,
        title=title,
        source_domain=source_domain,
        metadata_=metadata or {},
        discovered_via=discovered_via,
        discovered_by_user_id=discovered_by_user_id,
        confidence_score=0.6,
        success_count=0,
    )
    session.add(row)
    await session.flush()
    return row


async def increment_success(session: AsyncSession, item_id: uuid.UUID) -> None:
    # `synchronize_session=False` avoids the async-incompatible attribute-expire
    # pass — we don't reread the same columns from this object afterwards, and
    # the next request will load a fresh row anyway.
    await session.execute(
        update(CdaContentItem)
        .where(CdaContentItem.id == item_id)
        .values(
            success_count=CdaContentItem.success_count + 1,
            last_verified_at=datetime.now(timezone.utc),
            confidence_score=_recompute_confidence_sql(),
        )
        .execution_options(synchronize_session=False)
    )


async def increment_failure(session: AsyncSession, item_id: uuid.UUID) -> None:
    await session.execute(
        update(CdaContentItem)
        .where(CdaContentItem.id == item_id)
        .values(
            failure_count=CdaContentItem.failure_count + 1,
            confidence_score=_recompute_confidence_sql(),
        )
        .execution_options(synchronize_session=False)
    )


async def deactivate_item(session: AsyncSession, item_id: uuid.UUID) -> None:
    await session.execute(
        update(CdaContentItem)
        .where(CdaContentItem.id == item_id)
        .values(is_active=False)
        .execution_options(synchronize_session=False)
    )


async def attach_cached_answer(
    session: AsyncSession, item_id: uuid.UUID, answer_text: str
) -> None:
    """Save the natural-language answer the agent loop produced for this item.

    Stored under `metadata.cached_answer` so future identical questions can
    skip the second LLM pass (and even both passes if we early-bypass).
    """
    item = await session.get(CdaContentItem, item_id)
    if item is None:
        return
    item.metadata_ = {**(item.metadata_ or {}), "cached_answer": answer_text}
    await session.flush()


def _recompute_confidence_sql():
    """Bayesian-ish smoothing: (success+1) / (success + failure + 2)."""
    from sqlalchemy import case, cast, Float

    s = CdaContentItem.success_count
    f = CdaContentItem.failure_count
    return cast((s + 1), Float) / cast((s + f + 2), Float)


async def log_query(
    session: AsyncSession,
    *,
    user_id: int | None,
    raw_query: str,
    normalized_query: str,
    intent: dict[str, Any] | None,
    resolved_content_id: uuid.UUID | None,
    outcome: str,
    duration_ms: int,
    cached: bool,
) -> CdaQueryLog:
    row = CdaQueryLog(
        user_id=user_id,
        raw_query=raw_query,
        normalized_query=normalized_query,
        intent=intent,
        resolved_content_id=resolved_content_id,
        outcome=outcome,
        duration_ms=duration_ms,
        cached=cached,
    )
    session.add(row)
    await session.flush()
    return row
