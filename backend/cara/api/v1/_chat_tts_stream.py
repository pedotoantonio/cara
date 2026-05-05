"""Sentence-buffered TTS streaming (Step 1.3).

The chat endpoint streams LLM tokens as soon as they arrive (~5-9 tok/s
on the NPU). Without chunked TTS, the user sees text immediately but
hears nothing until the LLM finishes the whole response — that's
8-12 seconds of awkward silence on a long answer.

This module implements the missing piece: a `SentenceBuffer` that
accumulates incoming token text, detects sentence boundaries
("`.`/`!`/`?`/`\\n`"), and yields a complete sentence as soon as one
forms. The chat hot path can then call `synthesize(sentence, voice)`
and emit an SSE `audio_chunk` event alongside the text tokens.

The result: the user hears the *first* sentence about a second after
the LLM emits its terminal punctuation — typically 1.5-2 seconds into
the response, instead of 11 seconds.

This module ships the deterministic, async-free pieces:

  - `SentenceBuffer` — pure logic, no I/O.
  - `synthesize_sentence(text, voice_id)` — thin wrapper that calls the
    existing `cara.ai.tts.service` Piper path.
  - `audio_chunk_event(seq, text, audio_bytes, voice_id)` — formats the
    SSE payload (audio is base64-encoded WAV).

Wiring this into chat()'s stream() loop is a follow-up — gated behind
the `tts_streaming_enabled` admin flag (default OFF until the
frontend WebAudio queue lands).
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


# Sentence-boundary characters. We split on the FIRST one we see after
# a minimum-length threshold (avoids "Sig." or "es." mid-sentence
# triggering an early flush). The newline is included because the LLM
# often uses it as a paragraph break.
_TERMINAL_PUNCT = ".!?\n"

# Minimum chars in an emitted sentence. Below this, a period is held
# (likely abbreviation). "Sì." (3) → held; "Va bene." (8) → emitted.
_MIN_SENTENCE_CHARS = 6

# Hard ceiling: if the buffer grows past this without seeing a
# boundary, flush anyway. Keeps audio chunks bounded so a runaway LLM
# doesn't stall the audio pipeline.
_MAX_SENTENCE_CHARS = 400

# Things that look like sentence-end but aren't:
#   "es.", "p.es.", "Sig.", "Dr.", "ecc.", "n.",
#   trailing-number "22." (potential decimal still arriving),
#   confirmed decimal "1.5"
_ABBREV_RE = re.compile(
    r"\b(es|p\.es|sig|dr|sigg|prof|ecc|n)\.\s*$"
    r"|\b\d+\.\s*$"
    r"|\d+\.\d+$",
    re.IGNORECASE,
)


@dataclass
class SentenceBuffer:
    """Accumulate token text; emit complete sentences as soon as they form.

    Stateful, NOT async, NOT thread-safe. One instance per chat request.

    Usage:

        buf = SentenceBuffer()
        for chunk in llm_tokens:
            for sentence in buf.feed(chunk.text):
                yield audio_chunk_event(seq=N, text=sentence, ...)
        # Don't forget the tail at the end:
        for sentence in buf.flush():
            yield audio_chunk_event(seq=N, text=sentence, ...)
    """

    _buf: str = ""
    _seq: int = 0

    def feed(self, text: str) -> list[str]:
        """Append `text` and return any complete sentences ready to read.

        May return zero, one, or many sentences. Caller iterates and
        synthesises each.
        """
        if not text:
            return []
        self._buf += text
        out: list[str] = []
        while True:
            sentence = self._extract_one()
            if sentence is None:
                break
            out.append(sentence)
            self._seq += 1
        return out

    def flush(self) -> list[str]:
        """Return any leftover text in the buffer as a final sentence.

        Called once at the end of the stream so the user hears the
        last sentence even if the LLM didn't terminate it with
        punctuation.
        """
        leftover = self._buf.strip()
        self._buf = ""
        if not leftover:
            return []
        self._seq += 1
        return [leftover]

    @property
    def next_seq(self) -> int:
        return self._seq

    # ---------------------------------------------------------------- internals

    def _extract_one(self) -> str | None:
        """Look for the next sentence-end in `self._buf`. Return the
        sentence (left-of-break, including the punctuation) and rotate
        `self._buf` to start at the residue. Return None if not yet."""
        # Hard ceiling first — if the buffer is long enough, flush a
        # forced cut at the last whitespace before the limit.
        if len(self._buf) >= _MAX_SENTENCE_CHARS:
            cut = self._buf.rfind(" ", 0, _MAX_SENTENCE_CHARS)
            if cut < _MIN_SENTENCE_CHARS:
                cut = _MAX_SENTENCE_CHARS
            sentence = self._buf[:cut].strip()
            self._buf = self._buf[cut:].lstrip()
            return sentence or None

        # Find the first sentence-end whose emitted-sentence length
        # would be at least _MIN_SENTENCE_CHARS. Scanning starts at
        # index MIN-1 because a terminator at that index produces a
        # sentence of exactly MIN chars.
        for i in range(_MIN_SENTENCE_CHARS - 1, len(self._buf)):
            ch = self._buf[i]
            if ch not in _TERMINAL_PUNCT:
                continue
            chunk = self._buf[:i + 1]
            # Skip false positives: "es.", "Sig.", "1.5", etc.
            if _ABBREV_RE.search(chunk):
                continue
            sentence = chunk.strip()
            self._buf = self._buf[i + 1:].lstrip()
            return sentence or None
        return None


# ---------------------------------------------------------------------------
# SSE event helper
# ---------------------------------------------------------------------------


def audio_chunk_payload(
    *,
    seq: int,
    text: str,
    audio_bytes: bytes,
    voice_id: str,
    audio_format: str = "wav",
) -> dict[str, Any]:
    """Build the JSON payload for an `audio_chunk` SSE event.

    Audio is base64-encoded so it survives the text-only SSE channel.
    Frontend decodes + queues for sequential WebAudio playback.
    """
    return {
        "seq": seq,
        "text": text,
        "voice_id": voice_id,
        "format": audio_format,
        "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
        "bytes": len(audio_bytes),
    }


# ---------------------------------------------------------------------------
# Synthesis wrapper (lazy import the TTS service so unit tests don't need it)
# ---------------------------------------------------------------------------


async def synthesize_sentence(
    *,
    text: str,
    voice_id: str | None = None,
    normalizer=None,
) -> bytes:
    """Run the configured TTS engine on `text` and return WAV bytes.

    `normalizer` (optional) is a `TTSNormalizer` — when present, it
    rewrites anglicisms before synthesis. Caller passes
    `get_global_normalizer()` to share state across requests.

    The actual Piper invocation lives in `cara.ai.tts.service` (already
    in the project). We import it lazily so unit tests of
    `SentenceBuffer` don't need the Piper voice ONNX files on disk.
    """
    if normalizer is not None:
        text = normalizer.normalize(text)
    if not text.strip():
        return b""

    from cara.ai.tts.service import get_tts_service

    svc = get_tts_service()
    wav, _sample_rate = await svc.synthesize_wav(text=text, voice_id=voice_id)
    return wav


# ---------------------------------------------------------------------------
# High-level helper used by chat()
# ---------------------------------------------------------------------------


async def stream_audio_chunks(
    sentences: Iterable[str],
    *,
    voice_id: str,
    normalizer=None,
    starting_seq: int = 0,
):
    """Async generator: synthesise each sentence and yield SSE payloads.

    Designed to be `await`ed inside the chat stream() so the event
    interleaves cleanly with `token` and `done` events. Synthesis
    failures degrade silently (we log + skip the chunk; the user
    still sees the text).
    """
    import structlog
    log = structlog.get_logger(__name__)

    seq = starting_seq
    for sentence in sentences:
        try:
            audio = await synthesize_sentence(
                text=sentence, voice_id=voice_id, normalizer=normalizer,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("tts_stream.synthesize_failed", error=str(exc),
                        sentence_preview=sentence[:60])
            continue
        if not audio:
            continue
        yield audio_chunk_payload(
            seq=seq, text=sentence, audio_bytes=audio, voice_id=voice_id,
        )
        seq += 1
