"""Radio endpoints — catalogue + lookup. Gated by admin flag `radio_enabled`."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.services import admin_settings as setting_svc
from cara.services import radio as radio_svc
from cara.store import get_session

router = APIRouter(prefix="/radio", tags=["radio"])


class RadioStationOut(BaseModel):
    id: str
    name: str
    url: str
    genre: str
    country: str
    description: str


@router.get("", response_model=list[RadioStationOut])
async def list_stations(
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RadioStationOut]:
    enabled = await setting_svc.get(session, "radio_enabled")
    if not enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "La radio è disabilitata. Un admin deve attivarla.",
        )
    return [RadioStationOut(**asdict(s)) for s in radio_svc.all_stations()]


@router.get("/{station_id}", response_model=RadioStationOut)
async def get_station(
    station_id: str,
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RadioStationOut:
    enabled = await setting_svc.get(session, "radio_enabled")
    if not enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "La radio è disabilitata.")
    s = radio_svc.find_station(station_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stazione '{station_id}' non trovata.")
    return RadioStationOut(**asdict(s))
