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
        # Tuned for short Italian household utterances in noisy rooms:
        # beam_size=5 (vs greedy 1) roughly halves the empty-transcript
        # rate at the cost of ~30% latency; no_speech / compression
        # filters drop the classic "Sottotitoli e revisione" hallucination
        # loop on silence; condition_on_previous_text=False keeps each
        # turn independent; initial_prompt biases toward the household
        # lexicon. silero VAD threshold tightened so short answers
        # ("sì", "ok") still slip through.
        segments, info = model.transcribe(
            tmp_path,
            language=language,
            beam_size=5,
            condition_on_previous_text=False,
            no_speech_threshold=0.5,
            compression_ratio_threshold=2.4,
            initial_prompt=(
                "Conversazione familiare italiana con CARA, l'assistente "
                "di casa. Comandi brevi: accendi, spegni, ricordami, "
                "aggiungi alla spesa, metti, dimmi."
            ),
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 350,
                "threshold": 0.45,
            },
        )
        # Consume the generator AND collect per-segment confidence so
        # the frontend can decide whether to ask "Hai detto X?".
        texts: list[str] = []
        avg_logprobs: list[float] = []
        no_speech_probs: list[float] = []
        for seg in segments:
            texts.append(seg.text)
            if seg.avg_logprob is not None:
                avg_logprobs.append(float(seg.avg_logprob))
            if seg.no_speech_prob is not None:
                no_speech_probs.append(float(seg.no_speech_prob))
        text = "".join(texts).strip()
        avg_logprob = (
            sum(avg_logprobs) / len(avg_logprobs) if avg_logprobs else None
        )
        no_speech_prob = (
            sum(no_speech_probs) / len(no_speech_probs) if no_speech_probs else None
        )
        # Coarse-grain confidence label; the UI only needs three
        # buckets, not the raw logprobs.
        if not text:
            confidence_label = "empty"
        elif (
            (no_speech_prob is not None and no_speech_prob > 0.6)
            or (avg_logprob is not None and avg_logprob < -1.0)
        ):
            confidence_label = "low"
        elif (
            (no_speech_prob is not None and no_speech_prob > 0.3)
            or (avg_logprob is not None and avg_logprob < -0.6)
        ):
            confidence_label = "medium"
        else:
            confidence_label = "high"
        return {
            "text": text,
            "language": info.language,
            "duration_s": float(info.duration),
            "avg_logprob": avg_logprob,
            "no_speech_prob": no_speech_prob,
            "confidence_label": confidence_label,
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
        confidence=result.get("confidence_label"),
        avg_logprob=result.get("avg_logprob"),
        no_speech_prob=result.get("no_speech_prob"),
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
