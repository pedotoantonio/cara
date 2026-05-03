"""Server-side speech-to-text endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from cara.api.deps import get_current_user
from cara.config import settings
from cara.models.user import User
from cara.services import asr as asr_svc

router = APIRouter(prefix="/asr", tags=["asr"])


_MAX_AUDIO_BYTES = 8 * 1024 * 1024   # 8 MB → ~1 minute of WebM Opus 64 kbps


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),  # noqa: B008
    language: str = "it",
    _user: User = Depends(get_current_user),  # noqa: B008
) -> dict:
    """Accept an audio blob (WebM / WAV / MP3 / etc.), return the transcript."""
    if not settings.whisper_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Server-side ASR is disabled",
        )
    blob = await audio.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty audio")
    if len(blob) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"audio too large ({len(blob)} > {_MAX_AUDIO_BYTES} bytes)",
        )
    try:
        result = await asr_svc.transcribe_bytes(blob, language=language)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"transcription failed: {exc}",
        ) from exc
    return result
