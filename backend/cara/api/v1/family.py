"""Family endpoints — currently presence (who's home) via frigate-faces."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.services.family import FamilyPresenceUnavailable, people_present

router = APIRouter(prefix="/family", tags=["family"])


class PersonOut(BaseModel):
    name: str
    last_seen: datetime
    minutes_ago: int


class PresenceOut(BaseModel):
    window_minutes: int
    count: int
    people: list[PersonOut]


@router.get("/who-is-home", response_model=PresenceOut)
async def who_is_home(
    window_minutes: Annotated[int, Query(ge=1, le=1440)] = 15,
    _user: User = Depends(get_current_user),  # noqa: B008
) -> PresenceOut:
    try:
        rows = await people_present(window_minutes=window_minutes)
    except FamilyPresenceUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return PresenceOut(
        window_minutes=window_minutes,
        count=len(rows),
        people=[PersonOut(**asdict(p)) for p in rows],
    )
