"""REST endpoints for the Content Discovery Agent."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.cda import (
    CdaError,
    DiscoverRequest,
    discover as cda_discover,
    list_user_kb,
    record_feedback_regenerated,
    record_feedback_started,
    record_feedback_stopped,
)
from cara.models.user import User
from cara.store import get_session

router = APIRouter(prefix="/cda", tags=["cda"])


ContentTypeIn = Literal[
    "audio_stream", "article", "video", "podcast", "image", "document"
]


class DiscoverIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    content_type: ContentTypeIn
    modifiers: dict[str, Any] = Field(default_factory=dict)


class DiscoverOut(BaseModel):
    kind: str
    url: str
    title: str | None
    source_domain: str | None
    metadata: dict[str, Any]
    confidence: float
    cached: bool
    duration_ms_to_resolve: int
    content_id: uuid.UUID
    fallbacks: list[dict[str, Any]] = []


@router.post("/discover", response_model=DiscoverOut)
async def discover_endpoint(
    body: DiscoverIn,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DiscoverOut:
    try:
        result = await cda_discover(
            session,
            DiscoverRequest(
                user_id=user.id,
                raw_query=body.query,
                content_type=body.content_type,  # type: ignore[arg-type]
                modifiers=body.modifiers,
            ),
        )
    except CdaError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return DiscoverOut(
        kind=result.kind,
        url=result.url,
        title=result.title,
        source_domain=result.source_domain,
        metadata=result.metadata,
        confidence=result.confidence,
        cached=result.cached,
        duration_ms_to_resolve=result.duration_ms_to_resolve,
        content_id=result.content_id,
        fallbacks=[
            {
                "url": f.url,
                "title": f.title,
                "source_domain": f.source_domain,
                "score": f.score,
            }
            for f in result.fallbacks
        ],
    )


class KbItemOut(BaseModel):
    id: uuid.UUID
    content_type: str
    url: str
    title: str | None
    source_domain: str | None
    metadata: dict[str, Any]
    confidence_score: float
    success_count: int
    failure_count: int
    last_verified_at: datetime | None
    discovered_via: str | None
    discovered_at: datetime
    is_active: bool


@router.get("/items", response_model=list[KbItemOut])
async def items_endpoint(
    content_type: ContentTypeIn | Literal["article_feed"] | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[KbItemOut]:
    rows = await list_user_kb(
        session, user_id=user.id, content_type=content_type, limit=min(limit, 200)  # type: ignore[arg-type]
    )
    return [
        KbItemOut(
            id=r.id,
            content_type=r.content_type,
            url=r.url,
            title=r.title,
            source_domain=r.source_domain,
            metadata=r.metadata_ or {},
            confidence_score=float(r.confidence_score),
            success_count=r.success_count,
            failure_count=r.failure_count,
            last_verified_at=r.last_verified_at,
            discovered_via=r.discovered_via,
            discovered_at=r.discovered_at,
            is_active=r.is_active,
        )
        for r in rows
    ]


# ---- feedback endpoints -------------------------------------------------


class FeedbackStarted(BaseModel):
    content_id: uuid.UUID


class FeedbackStopped(BaseModel):
    content_id: uuid.UUID
    played_seconds: float = Field(..., ge=0)
    reason: Literal["user_stop", "ended", "error", "switched"] = "user_stop"


class FeedbackRegenerated(BaseModel):
    content_id: uuid.UUID


@router.post("/feedback/started", status_code=status.HTTP_204_NO_CONTENT)
async def feedback_started(
    body: FeedbackStarted,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    await record_feedback_started(session, body.content_id)


@router.post("/feedback/stopped", status_code=status.HTTP_204_NO_CONTENT)
async def feedback_stopped(
    body: FeedbackStopped,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    await record_feedback_stopped(
        session,
        content_id=body.content_id,
        played_seconds=body.played_seconds,
        reason=body.reason,
    )


@router.post("/feedback/regenerated", status_code=status.HTTP_204_NO_CONTENT)
async def feedback_regenerated(
    body: FeedbackRegenerated,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    await record_feedback_regenerated(session, body.content_id)
