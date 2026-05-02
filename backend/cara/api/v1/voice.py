"""Voice (TTS) configuration and server-side synthesis.

Two layers:

1. **Browser TTS knobs** (`/voice/config`): when a client uses the browser
   `SpeechSynthesisUtterance`, the admin-set name/rate/pitch/volume act as
   the global preferences.

2. **Piper server-side TTS** (`/voice/voices`, `/voice/synthesize`): when the
   client picks the "voce CARA" engine, the backend renders WAV via Piper
   and ships it. The catalog comes from the loaded `TTSService`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai.tts import get_tts_service
from cara.api.deps import get_current_user
from cara.config import settings
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


# ---- Piper server-side TTS ------------------------------------------


class VoiceCatalogEntry(BaseModel):
    id: str
    engine: str
    display_name: str
    language: str
    locale: str
    gender: str | None = None
    quality: str
    sample_rate: int
    license: str
    size_mb: int | None = None
    description: str | None = None


@router.get("/voices", response_model=list[VoiceCatalogEntry])
async def list_voices(
    _user: User = Depends(get_current_user),  # noqa: B008
) -> list[dict]:
    try:
        svc = get_tts_service()
    except RuntimeError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TTS service not available on this deployment.",
        )
    return svc.list_voices()


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    voice_id: str | None = None     # "engine:voice_id"; None = default
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


@router.get("/default", response_model=dict)
async def get_default_voice(_user: User = Depends(get_current_user)) -> dict:  # noqa: B008
    return {"voice_id": settings.tts_default_voice}


@router.post("/synthesize")
async def synthesize(
    body: SynthesizeRequest,
    _user: User = Depends(get_current_user),  # noqa: B008
) -> Response:
    """Render `text` to a WAV audio file and return the bytes.

    Cached server-side for short repeated phrases (see `tts_cache_max_chars`).
    """
    try:
        svc = get_tts_service()
    except RuntimeError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TTS unavailable")
    try:
        wav, sample_rate = await svc.synthesize_wav(
            text=body.text,
            voice_id=body.voice_id,
            speed=body.speed,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if not wav:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty text")
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "X-Sample-Rate": str(sample_rate),
            "X-Audio-Bytes": str(len(wav)),
        },
    )
