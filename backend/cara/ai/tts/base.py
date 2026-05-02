"""TTS engine abstractions.

Every concrete engine (Piper, XTTS-v2, Sherpa-ONNX, …) implements `TTSEngine`.
Voices are addressed by an opaque `voice_id` whose grammar is engine-defined
(e.g. `it_IT-paola-medium` for Piper). The `TTSService` orchestrator routes a
fully-qualified id like `piper:it_IT-paola-medium` to the right engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class VoiceInfo:
    """Metadata for one voice in an engine's catalog."""

    id: str                     # e.g. "it_IT-paola-medium"
    display_name: str           # "Paola"
    language: str               # ISO 639-1 ("it", "en")
    locale: str                 # BCP-47 ("it_IT", "en_GB")
    gender: str | None          # "f" | "m" | None
    quality: str                # "x_low" | "low" | "medium" | "high"
    sample_rate: int            # 16000 | 22050
    license: str                # SPDX id ("MIT", "CPML-non-commercial")
    size_mb: int | None = None  # download size, when applicable
    description: str | None = None


@dataclass
class TTSRequest:
    text: str
    voice_id: str               # engine-internal voice id (no engine prefix)
    speed: float = 1.0          # 0.5 .. 2.0
    pitch: float = 1.0          # 0.0 .. 2.0 (informational; Piper ignores)
    volume: float = 1.0         # 0.0 .. 1.0 (informational; rendered client-side)
    sample_rate: int | None = None


@dataclass
class TTSChunk:
    """One frame of synthesized audio. PCM int16 little-endian, mono."""

    pcm: bytes
    sample_rate: int
    is_final: bool


class TTSEngine(ABC):
    """Abstract TTS engine."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short engine id used as the prefix in fully-qualified voice ids."""

    @property
    @abstractmethod
    def license(self) -> str:
        """SPDX id of the engine's license."""

    @property
    @abstractmethod
    def supports_voice_cloning(self) -> bool: ...

    @abstractmethod
    def list_voices(self) -> list[VoiceInfo]:
        """Catalog of voices this engine can serve (may include not-yet-downloaded)."""

    @abstractmethod
    async def synthesize(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        """Stream synthesized PCM audio chunk-by-chunk."""
