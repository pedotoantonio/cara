"""TTS service orchestrator.

Routes a fully-qualified `voice_id` like `piper:it_IT-paola-medium` to the
right engine, applies a Redis cache for short repeated phrases, and yields a
WAV-wrapped audio stream so the frontend can drop the bytes straight into a
`<audio>` element or Web Audio API.

Single global instance, initialized in the FastAPI lifespan (see main.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import struct
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import structlog

from cara.ai.tts.base import TTSChunk, TTSEngine, TTSRequest, VoiceInfo
from cara.ai.tts.engines.piper import PiperEngine

log = structlog.get_logger(__name__)


def _wav_header(num_samples: int, sample_rate: int, channels: int = 1, sampwidth: int = 2) -> bytes:
    """Build a minimal RIFF/WAVE header for PCM int16 mono."""
    byte_rate = sample_rate * channels * sampwidth
    block_align = channels * sampwidth
    data_size = num_samples * channels * sampwidth
    riff_size = 36 + data_size
    return (
        b"RIFF"
        + struct.pack("<I", riff_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + struct.pack("<H", 1)        # PCM
        + struct.pack("<H", channels)
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", byte_rate)
        + struct.pack("<H", block_align)
        + struct.pack("<H", sampwidth * 8)
        + b"data"
        + struct.pack("<I", data_size)
    )


def _wav_from_pcm(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM int16 mono bytes in a WAV container, in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class TTSService:
    """Front of the TTS subsystem. One instance per process."""

    def __init__(
        self,
        engines: dict[str, TTSEngine],
        default_voice_id: str,
        cache_ttl: int = 3600,
        cache_max_chars: int = 400,
    ):
        self.engines = engines
        self.default_voice_id = default_voice_id
        self.cache_ttl = cache_ttl
        self.cache_max_chars = cache_max_chars
        self._redis = None  # set lazily
        self._redis_url: str | None = None

    def attach_redis_url(self, url: str) -> None:
        self._redis_url = url

    async def _redis_client(self):  # type: ignore[no-untyped-def]
        if self._redis is None and self._redis_url:
            import redis.asyncio as aioredis  # local import to keep startup snappy

            self._redis = aioredis.from_url(self._redis_url, decode_responses=False)
        return self._redis

    # ---- catalog ------------------------------------------------------

    def list_voices(self) -> list[dict[str, object]]:
        """Flat list of all voices across engines, with engine prefix in id."""
        out: list[dict[str, object]] = []
        for engine_name, engine in self.engines.items():
            for v in engine.list_voices():
                out.append(
                    {
                        "id": f"{engine_name}:{v.id}",
                        "engine": engine_name,
                        "display_name": v.display_name,
                        "language": v.language,
                        "locale": v.locale,
                        "gender": v.gender,
                        "quality": v.quality,
                        "sample_rate": v.sample_rate,
                        "license": v.license,
                        "size_mb": v.size_mb,
                        "description": v.description,
                    }
                )
        return out

    # ---- synthesis ----------------------------------------------------

    def _resolve(self, voice_id: str | None) -> tuple[TTSEngine, str]:
        vid = voice_id or self.default_voice_id
        if ":" not in vid:
            raise ValueError(f"voice id must be 'engine:voice_id', got {vid!r}")
        engine_name, voice_ref = vid.split(":", 1)
        engine = self.engines.get(engine_name)
        if engine is None:
            raise ValueError(f"unknown engine: {engine_name}")
        return engine, voice_ref

    @staticmethod
    def _cache_key(voice_id: str, text: str, speed: float) -> str:
        h = hashlib.sha256()
        h.update(voice_id.encode())
        h.update(b"|")
        h.update(f"{speed:.3f}".encode())
        h.update(b"|")
        h.update(text.encode())
        return f"tts:v1:{h.hexdigest()}"

    async def synthesize_wav(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> tuple[bytes, int]:
        """Synthesize the full text and return (wav_bytes, sample_rate).

        Cached in Redis when the text is short enough that caching is worth
        more than re-synthesis (`tts_cache_max_chars`).
        """
        engine, voice_ref = self._resolve(voice_id)
        full_id = f"{engine.name}:{voice_ref}"
        clean_text = text.strip()
        if not clean_text:
            return b"", 0

        cacheable = len(clean_text) <= self.cache_max_chars
        cache_key = self._cache_key(full_id, clean_text, speed) if cacheable else None
        client = await self._redis_client() if cache_key else None
        if client and cache_key:
            try:
                cached = await client.get(cache_key)
                if cached:
                    # First 4 bytes hold the sample rate; the rest is WAV.
                    sr = int.from_bytes(cached[:4], "little")
                    log.debug("tts.cache.hit", voice=full_id, chars=len(clean_text))
                    return cached[4:], sr
            except Exception as exc:  # noqa: BLE001
                log.warning("tts.cache.read_error", error=str(exc))

        # Synthesize end-to-end and accumulate PCM.
        pcm = bytearray()
        sample_rate = 22050
        request = TTSRequest(text=clean_text, voice_id=voice_ref, speed=speed)
        async for ch in engine.synthesize(request):
            if ch.is_final:
                break
            pcm.extend(ch.pcm)
            sample_rate = ch.sample_rate

        wav = _wav_from_pcm(bytes(pcm), sample_rate)

        if client and cache_key:
            try:
                # Prepend 4-byte sample rate marker so we can recover it on hit.
                payload = sample_rate.to_bytes(4, "little") + wav
                await client.set(cache_key, payload, ex=self.cache_ttl)
            except Exception as exc:  # noqa: BLE001
                log.warning("tts.cache.write_error", error=str(exc))

        return wav, sample_rate

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> AsyncIterator[bytes]:
        """Async generator yielding raw PCM chunks for streaming responses.

        The first chunk is the WAV header (with a placeholder data size set to
        the maximum so audio decoders happily start playing while we keep
        appending). The rest are PCM int16 little-endian frames.
        """
        engine, voice_ref = self._resolve(voice_id)
        clean_text = text.strip()
        if not clean_text:
            return

        # We can't know the total length in advance; ship a streaming-friendly
        # WAV header with a "huge" placeholder data size so players keep
        # consuming until the connection closes.
        sample_rate_holder: list[int] = []
        request = TTSRequest(text=clean_text, voice_id=voice_ref, speed=speed)
        first = True
        async for ch in engine.synthesize(request):
            if ch.is_final:
                break
            if first:
                sample_rate_holder.append(ch.sample_rate)
                # 0xFFFFFFFF is the conventional "unknown length" marker.
                yield _wav_header(num_samples=0xFFFFFFFF // 2, sample_rate=ch.sample_rate)
                first = False
            yield bytes(ch.pcm)


# ---- module-level singleton ------------------------------------------


_service: TTSService | None = None


def get_tts_service() -> TTSService:
    if _service is None:
        raise RuntimeError("TTS service not initialized; call init_tts_service first")
    return _service


async def init_tts_service(voices_dir: str, default_voice: str, redis_url: str,
                           cache_ttl: int = 3600, cache_max_chars: int = 400) -> TTSService:
    global _service
    piper = PiperEngine(voices_dir=Path(voices_dir))
    svc = TTSService(
        engines={"piper": piper},
        default_voice_id=default_voice,
        cache_ttl=cache_ttl,
        cache_max_chars=cache_max_chars,
    )
    svc.attach_redis_url(redis_url)
    _service = svc
    log.info("tts.service.initialized", default=default_voice, voices_dir=voices_dir)
    # Best-effort warm-up: pre-load default voice (downloads on first run).
    try:
        engine_name, voice_ref = default_voice.split(":", 1)
        eng = svc.engines.get(engine_name)
        if isinstance(eng, PiperEngine):
            asyncio.create_task(eng._load_voice(voice_ref))
    except Exception as exc:  # noqa: BLE001
        log.warning("tts.warmup.skipped", error=str(exc))
    return svc


async def shutdown_tts_service() -> None:
    global _service
    if _service is None:
        return
    if _service._redis is not None:
        try:
            await _service._redis.close()
        except Exception:  # noqa: BLE001
            pass
    _service = None
