"""Audio helpers for the Telegram bot.

Two conversions:
- `wav_to_opus_ogg(wav)` → bytes: WAV from Piper into the OGG/Opus
  container Telegram requires for voice notes (`send_voice`).
  Streamed through `ffmpeg -c:a libopus -f ogg` via stdin/stdout pipes
  so we avoid temp files. ~50 ms per second of audio on the NanoPC.
- `download_telegram_audio(file_id)` → bytes: pulls the original
  user-recorded blob (also OGG/Opus from the Telegram side) so the
  ASR endpoint can transcribe it.

The dispatcher uses `wav_to_opus_ogg` after Piper synth when the
admin enables `notify_voice_message_enabled`. The `_on_voice` handler
uses the download helper followed by Whisper STT.
"""

from __future__ import annotations

import asyncio
import structlog


log = structlog.get_logger(__name__)


async def wav_to_opus_ogg(wav: bytes) -> bytes | None:
    """Transcode a complete WAV blob to OGG/Opus, return the bytes.
    Returns None on failure — callers should fall back to text-only.
    """
    if not wav:
        return None
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-loglevel", "error",
        "-i", "pipe:0",
        "-c:a", "libopus",
        "-b:a", "32k",
        "-application", "voip",
        "-f", "ogg",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(input=wav), timeout=15.0
        )
    except asyncio.TimeoutError:
        log.warning("telegram_audio.transcode_timeout", wav_size=len(wav))
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return None
    if proc.returncode != 0:
        log.warning(
            "telegram_audio.transcode_failed",
            rc=proc.returncode,
            stderr=err.decode("utf-8", errors="replace")[:200],
        )
        return None
    return out


async def synth_voice_note(text: str) -> bytes | None:
    """Synthesise text via Piper, then transcode WAV → OGG/Opus.
    Returns the OGG bytes ready to feed `bot.send_voice(voice=...)`,
    or None when either stage fails."""
    if not text or not text.strip():
        return None
    try:
        from cara.ai.tts.service import get_tts_service  # noqa: PLC0415
        svc = get_tts_service()
        wav, _sr = await svc.synthesize_wav(text=text)
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram_audio.synthesize_failed", error=str(exc))
        return None
    if not wav:
        return None
    return await wav_to_opus_ogg(wav)
