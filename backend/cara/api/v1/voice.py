"""Voice (TTS) configuration — readable by any authenticated user.

The actual TTS happens in the browser via `SpeechSynthesisUtterance`, so the
backend only stores admin-set knobs (voice name preference, rate, pitch,
volume) and exposes them here. The frontend caches the response on app
start and applies the values whenever it speaks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.services import admin_settings as setting_svc
from cara.store import get_session

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceConfig(BaseModel):
    name: str | None = None
    rate: float | None = None
    pitch: float | None = None
    volume: float | None = None


def _as_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@router.get("/config", response_model=VoiceConfig)
async def get_voice_config(
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> VoiceConfig:
    name = await setting_svc.get(session, "voice_name")
    return VoiceConfig(
        name=name if isinstance(name, str) and name.strip() else None,
        rate=_as_float(await setting_svc.get(session, "voice_rate")),
        pitch=_as_float(await setting_svc.get(session, "voice_pitch")),
        volume=_as_float(await setting_svc.get(session, "voice_volume")),
    )
