"""TTS (text-to-speech) subsystem.

Multi-engine architecture: every engine implements `TTSEngine` (see `base.py`).
Today only Piper is wired up; the abstract base is here so a second engine
(XTTS-v2 voice cloning, Sherpa-ONNX on NPU, …) can be added without touching
call sites.
"""

from cara.ai.tts.base import (
    TTSChunk,
    TTSEngine,
    TTSRequest,
    VoiceInfo,
)
from cara.ai.tts.engines.piper import PiperEngine
from cara.ai.tts.service import TTSService, get_tts_service, init_tts_service, shutdown_tts_service

__all__ = [
    "TTSChunk",
    "TTSEngine",
    "TTSRequest",
    "TTSService",
    "VoiceInfo",
    "PiperEngine",
    "get_tts_service",
    "init_tts_service",
    "shutdown_tts_service",
]
