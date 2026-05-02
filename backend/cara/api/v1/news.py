"""News endpoint — gated by admin flag `news_enabled` (default off)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.services import admin_settings as setting_svc
from cara.services import news as news_svc
from cara.store import get_session

router = APIRouter(prefix="/news", tags=["news"])


class NewsItemOut(BaseModel):
    title: str
    summary: str
    link: str
    source: str
    published: str | None


class NewsResponse(BaseModel):
    category: str
    count: int
    items: list[NewsItemOut]
    digest: str   # TTS-friendly Italian summary of the top items


Category = Literal["all", "italia", "mondo", "economia", "tech", "sport"]


@router.get("", response_model=NewsResponse)
async def get_news(
    category: Annotated[Category, Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=50)] = 15,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> NewsResponse:
    enabled = await setting_svc.get(session, "news_enabled")
    if not enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Le news sono disabilitate. Un admin deve attivarle.",
        )
    items = await news_svc.fetch_category(category, limit=limit)
    return NewsResponse(
        category=category,
        count=len(items),
        items=[NewsItemOut(**asdict(it)) for it in items],
        digest=news_svc.make_digest(items, category=category),
    )
