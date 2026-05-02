"""Inferred per-user preferences (preferred_radio, preferred_news_source, …)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.cda import CdaUserPreference


async def get_preference(
    session: AsyncSession, *, user_id: int, preference_type: str, min_confidence: float = 0.7
) -> CdaUserPreference | None:
    stmt = (
        select(CdaUserPreference)
        .where(
            CdaUserPreference.user_id == user_id,
            CdaUserPreference.preference_type == preference_type,
            CdaUserPreference.confidence >= min_confidence,
        )
        .order_by(desc(CdaUserPreference.confidence))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_preference(
    session: AsyncSession,
    *,
    user_id: int,
    preference_type: str,
    preference_value: str,
    confidence: float,
    sample_count: int,
) -> CdaUserPreference:
    existing = await session.get(
        CdaUserPreference, (user_id, preference_type, preference_value)
    )
    if existing is None:
        existing = CdaUserPreference(
            user_id=user_id,
            preference_type=preference_type,
            preference_value=preference_value,
            confidence=confidence,
            sample_count=sample_count,
            last_observed_at=datetime.now(timezone.utc),
        )
        session.add(existing)
    else:
        existing.confidence = confidence
        existing.sample_count = sample_count
        existing.last_observed_at = datetime.now(timezone.utc)
    await session.flush()
    return existing
