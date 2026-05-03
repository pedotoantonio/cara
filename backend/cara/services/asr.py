"""Server-side speech-to-text via `faster-whisper`.

Used as a fallback when the browser SpeechRecognition API doesn't produce a
final transcript (iOS Safari is the typical culprit). The frontend records
the user's audio with `MediaRecorder` and uploads the blob; we transcribe
locally and return the text.

Lazy load: the model is loaded on first request (~5-10 s for `small`),
then kept in memory. CTranslate2 with int8 quantisation gives ~1-2 GB RAM
and ~0.2x real-time on RK3588 CPU.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import structlog

from cara.config import settings

log = structlog.get_logger(__name__)


_model: Any = None        # faster_whisper.WhisperModel
_load_lock: asyncio.Lock = asyncio.Lock()


async def _ensure_model() -> Any:
    """Lazy load the Whisper model. Single instance per process."""
    global _model
    if _model is not None:
        return _model
    async with _load_lock:
        if _model is not None:
            return _model
        # Import inside the lock to avoid loading CTranslate2 at process boot.
        from faster_whisper import WhisperModel

        cache_dir = settings.whisper_cache_dir
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        log.info(
            "asr.whisper.load.start",
            model=settings.whisper_model,
            cache_dir=cache_dir,
            compute_type=settings.whisper_compute_type,
        )
        t0 = time.monotonic()
        # Run the (blocking, CPU-bound) model load in a thread.
        _model = await asyncio.to_thread(
            WhisperModel,
            settings.whisper_model,
            device="cpu",
            compute_type=settings.whisper_compute_type,
            download_root=cache_dir,
            local_files_only=False,
        )
        log.info("asr.whisper.load.done", seconds=round(time.monotonic() - t0, 2))
        return _model


async def transcribe_bytes(audio_bytes: bytes, language: str | None = "it") -> dict[str, Any]:
    """Transcribe an audio blob (any ffmpeg-supported format).

    Returns: {"text": str, "language": str, "duration_s": float, "elapsed_ms": int}
    """
    model = await _ensure_model()
    t0 = time.monotonic()

    # Write the bytes to a tempfile because faster-whisper needs a file path
    # or numpy array; the path is the simplest cross-format way (ffmpeg
    # auto-decodes WebM/MP4/WAV etc).
    import tempfile

    suffix = ".webm"     # MediaRecorder default; ffmpeg handles container detection
    with tempfile.NamedTemporaryFile(prefix="cara-asr-", suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    def _run() -> dict[str, Any]:
        segments, info = model.transcribe(
            tmp_path,
            language=language,
            beam_size=1,        # greedy = faster, accuracy still fine for short utterances
            vad_filter=True,    # voice-activity detection: skip silence at edges
            vad_parameters={"min_silence_duration_ms": 500},
        )
        # `segments` is a generator; consume it.
        text = "".join(seg.text for seg in segments).strip()
        return {
            "text": text,
            "language": info.language,
            "duration_s": float(info.duration),
        }

    try:
        result = await asyncio.to_thread(_run)
    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass

    result["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    log.info(
        "asr.whisper.transcribe.done",
        elapsed_ms=result["elapsed_ms"],
        text_chars=len(result["text"]),
        duration_s=round(result["duration_s"], 2),
    )
    # Mirror to the in-memory event log so the admin diagnostics page
    # can show recent ASR activity without requiring `docker logs`.
    try:
        from cara.services import event_log
        event_log.record(
            "asr.whisper",
            duration_ms=result["elapsed_ms"],
            text_chars=len(result["text"]),
            audio_duration_s=round(result["duration_s"], 2),
            language=result.get("language"),
        )
    except Exception:  # noqa: BLE001
        pass
    return result
