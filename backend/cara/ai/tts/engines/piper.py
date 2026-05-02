"""Piper TTS engine.

Piper (https://github.com/rhasspy/piper) is an MIT-licensed neural TTS
optimized for low-power CPUs. We use it as CARA's default voice because:
- italiano nativo (Paola medium, Riccardo x_low) — same Lumo uses;
- MIT license — no constraint on commercial redistribution;
- RTF ~0.05 on the NanoPC-T6 CPU, no NPU required (NPU stays free for the LLM);
- ~50–100 MB RAM per loaded voice.

Voices ship as `.onnx` (model) + `.onnx.json` (config) pairs. They live under
`TTS_VOICES_DIR` (defaults to `/app/tts/piper/voices` in the container) and
are downloaded on demand from HuggingFace `rhasspy/piper-voices` the first
time a given voice is requested.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import structlog

from cara.ai.tts.base import TTSChunk, TTSEngine, TTSRequest, VoiceInfo

log = structlog.get_logger(__name__)


# Static catalog of voices we expose (B-level scope: 3 voices).
# Each entry maps to files at:
#   https://huggingface.co/rhasspy/piper-voices/resolve/main/{relpath}.onnx
#   https://huggingface.co/rhasspy/piper-voices/resolve/main/{relpath}.onnx.json
_CATALOG: list[dict[str, Any]] = [
    {
        "id": "it_IT-paola-medium",
        "display_name": "Paola",
        "language": "it",
        "locale": "it_IT",
        "gender": "f",
        "quality": "medium",
        "sample_rate": 22050,
        "size_mb": 60,
        "relpath": "it/it_IT/paola/medium/it_IT-paola-medium",
        "description": "Voce italiana femminile, qualità media. Stessa di Lumo.",
    },
    {
        "id": "it_IT-riccardo-x_low",
        "display_name": "Riccardo",
        "language": "it",
        "locale": "it_IT",
        "gender": "m",
        "quality": "x_low",
        "sample_rate": 16000,
        "size_mb": 20,
        "relpath": "it/it_IT/riccardo/x_low/it_IT-riccardo-x_low",
        "description": "Voce italiana maschile, qualità bassa ma molto leggera.",
    },
    {
        "id": "en_GB-alba-medium",
        "display_name": "Alba",
        "language": "en",
        "locale": "en_GB",
        "gender": "f",
        "quality": "medium",
        "sample_rate": 22050,
        "size_mb": 60,
        "relpath": "en/en_GB/alba/medium/en_GB-alba-medium",
        "description": "British English female voice.",
    },
]

_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def _catalog_by_id(voice_id: str) -> dict[str, Any] | None:
    for v in _CATALOG:
        if v["id"] == voice_id:
            return v
    return None


class PiperEngine(TTSEngine):
    name = "piper"
    license = "MIT"
    supports_voice_cloning = False

    def __init__(self, voices_dir: Path):
        self.voices_dir = voices_dir
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self._loaded: dict[str, Any] = {}     # voice_id -> PiperVoice
        # One lock per voice so concurrent downloads of different voices don't
        # serialize, but two requests for the same voice share work.
        self._download_locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    # ---- catalog ------------------------------------------------------

    def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(
                id=v["id"],
                display_name=v["display_name"],
                language=v["language"],
                locale=v["locale"],
                gender=v.get("gender"),
                quality=v["quality"],
                sample_rate=v["sample_rate"],
                license=self.license,
                size_mb=v.get("size_mb"),
                description=v.get("description"),
            )
            for v in _CATALOG
        ]

    # ---- voice loading / download ------------------------------------

    def _files_for(self, voice_id: str) -> tuple[Path, Path]:
        return (
            self.voices_dir / f"{voice_id}.onnx",
            self.voices_dir / f"{voice_id}.onnx.json",
        )

    async def _download_lock_for(self, voice_id: str) -> asyncio.Lock:
        async with self._global_lock:
            if voice_id not in self._download_locks:
                self._download_locks[voice_id] = asyncio.Lock()
            return self._download_locks[voice_id]

    async def _ensure_files(self, voice_id: str) -> tuple[Path, Path]:
        meta = _catalog_by_id(voice_id)
        if meta is None:
            raise ValueError(f"unknown piper voice id: {voice_id}")
        onnx_path, cfg_path = self._files_for(voice_id)
        if onnx_path.exists() and cfg_path.exists():
            return onnx_path, cfg_path
        lock = await self._download_lock_for(voice_id)
        async with lock:
            # Re-check after acquiring the lock.
            if onnx_path.exists() and cfg_path.exists():
                return onnx_path, cfg_path
            log.info("tts.piper.download.start", voice_id=voice_id)
            relpath = meta["relpath"]
            urls = [
                (f"{_HF_BASE}/{relpath}.onnx", onnx_path),
                (f"{_HF_BASE}/{relpath}.onnx.json", cfg_path),
            ]
            async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
                for url, dest in urls:
                    log.info("tts.piper.download.fetch", url=url)
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    async with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        with tmp.open("wb") as f:
                            async for chunk in resp.aiter_bytes(64 * 1024):
                                f.write(chunk)
                    tmp.replace(dest)
            log.info("tts.piper.download.done", voice_id=voice_id, size=onnx_path.stat().st_size)
            return onnx_path, cfg_path

    async def _load_voice(self, voice_id: str) -> Any:
        if voice_id in self._loaded:
            return self._loaded[voice_id]
        onnx_path, _ = await self._ensure_files(voice_id)
        # Piper python package; loading is sync and quick (~200ms for medium).
        loop = asyncio.get_running_loop()

        def _load() -> Any:
            from piper import PiperVoice
            return PiperVoice.load(str(onnx_path))

        v = await loop.run_in_executor(None, _load)
        self._loaded[voice_id] = v
        log.info("tts.piper.voice.loaded", voice_id=voice_id)
        return v

    # ---- synthesis ----------------------------------------------------

    async def synthesize(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        from piper import SynthesisConfig

        voice = await self._load_voice(request.voice_id)
        # Piper's `length_scale` is *inverse* of speed: 1.0 = normal, lower = faster.
        length_scale = max(0.1, min(2.5, 1.0 / max(0.1, request.speed)))
        syn = SynthesisConfig(
            length_scale=length_scale,
            noise_scale=0.667,
            noise_w_scale=0.8,
            volume=max(0.0, min(1.0, request.volume)),
        )

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[bytes, int] | None] = asyncio.Queue(maxsize=64)

        def _produce() -> None:
            try:
                for chunk in voice.synthesize(request.text, syn_config=syn):
                    pcm = bytes(chunk.audio_int16_bytes)
                    if pcm:
                        loop.call_soon_threadsafe(
                            queue.put_nowait, (pcm, int(chunk.sample_rate))
                        )
            except Exception as exc:  # noqa: BLE001
                log.warning("tts.piper.synth.error", error=str(exc))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, _produce)

        sample_rate = 22050
        while True:
            item = await queue.get()
            if item is None:
                yield TTSChunk(pcm=b"", sample_rate=sample_rate, is_final=True)
                return
            pcm, sample_rate = item
            yield TTSChunk(pcm=pcm, sample_rate=sample_rate, is_final=False)
