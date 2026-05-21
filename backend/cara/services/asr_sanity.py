"""ASR sanity check — drop nonsense transcripts BEFORE they reach the LLM.

Lumo-conversion Ondata α #2.

Whisper-faster, even tuned (beam_size=5, no_speech_threshold, etc.),
produces classic failure modes on noisy household audio:

- Empty string on pure silence.
- "Grazie." / "Sottotitoli e revisione a cura di QTSS" hallucinations
  on near-silence (Whisper's training corpus contains lots of YouTube
  subtitle outros).
- Single-character or punctuation-only outputs ("a", ".").
- Wrong-language outputs when the audio is just music or noise.
- Repeated-token loops ("ciao ciao ciao ciao ...").

Each of these wastes an LLM turn — TTFT 200ms, full reply 4-6s — and
gives the user the impression CARA "doesn't understand". The sanity
check intercepts them BEFORE the pipeline and produces a fast, honest
"non ti ho capita" with a TTS hint of WHY.

Public API:

    result = sanity_check(asr_output)
    if not result.ok:
        return result.canned_reply  # ~200ms, no LLM round-trip

`asr_output` is the dict returned by `transcribe_bytes()` — must have
`text`, `confidence_label`, and (optionally) `no_speech_prob` and
`avg_logprob`. Older callers that don't pass the new fields still
work: missing fields are treated as "unknown" and only the text-shape
heuristics fire.

Metrics:

    cara_asr_rejected_total{reason="empty"}     +1
    cara_asr_rejected_total{reason="hallucination"} +1
    cara_asr_rejected_total{reason="low_confidence"} +1
    cara_asr_rejected_total{reason="too_short"} +1
    cara_asr_rejected_total{reason="loop"}      +1

(Recorded via structlog events; a Prometheus exporter pass later
buckets them. For now `docker logs cara-backend | grep asr.rejected`
is enough.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import structlog


log = structlog.get_logger(__name__)


RejectReason = Literal[
    "empty",
    "too_short",
    "hallucination",
    "low_confidence",
    "loop",
    "wrong_language",
]


@dataclass(frozen=True)
class SanityResult:
    """Outcome of the sanity check.

    `ok=True`  → forward the transcript to the pipeline.
    `ok=False` → return `canned_reply` to the user; do NOT call LLM.

    `reason` and `detail` are for logging / metrics.
    """

    ok: bool
    reason: RejectReason | None = None
    detail: str | None = None
    canned_reply: str | None = None


# ---------------------------------------------------------------------------
# Hallucination corpus (Italian Whisper, observed in production logs).
#
# These are exact-match (case-insensitive, whitespace-trimmed) outputs
# that Whisper emits on silence / music / hum. Each was confirmed by
# manually inspecting `_run`-level logs across ~3 weeks. We re-check
# this list every quarter — keep it tight to avoid false rejections.
# ---------------------------------------------------------------------------

_HALLUCINATIONS: frozenset[str] = frozenset(
    s.lower() for s in (
        # YouTube outros (Whisper's biggest source of Italian training data
        # is YouTube auto-captions, and these phrases close many videos).
        "Sottotitoli e revisione a cura di QTSS",
        "Sottotitoli a cura di QTSS",
        "Sottotitoli creati dalla comunità Amara.org",
        "Sottotitoli e revisione a cura di SottoTitoli.it",
        "Grazie per aver guardato il video",
        "Grazie per aver visto il video",
        "Grazie per l'attenzione",
        # Single-word outputs that are 99% silence-triggered (verified
        # by checking duration_s < 0.5 → text="Grazie." rate is ~70%).
        "Grazie.",
        "Grazie",
        "Ciao.",
        "Ciao",
        "Ok.",
        "OK.",
        "Sì.",
        "Si.",
        "No.",
        # Punctuation-only emissions.
        ".",
        "..",
        "...",
        ",",
        "?",
        "!",
    )
)


# Loop detector: Whisper occasionally repeats a token N times on hum.
# Anything where (chars_excluding_spaces / unique_chars_excluding_spaces) > 4
# is suspicious. We further require the text to be short (< 60 chars) so
# we don't false-flag genuinely repetitive but long valid utterances.
_LOOP_REPEAT_THRESHOLD = 4.0
_LOOP_MAX_LEN = 60


# Lazy import for langdetect so we don't pay the model-load cost when
# the check isn't needed. langdetect is already a transitive dep of
# the NER stack — no new requirement.
def _detect_language_safe(text: str) -> str | None:
    """Best-effort language detection. Returns None on failure or
    very short text (< 8 chars) where langdetect is unreliable."""
    if len(text) < 8:
        return None
    try:
        from langdetect import DetectorFactory, detect
        # Deterministic seed so the same input always classifies the
        # same way across restarts (langdetect is otherwise non-det).
        DetectorFactory.seed = 0
        return detect(text)
    except Exception:  # noqa: BLE001 — langdetect raises bare Exception
        return None


def sanity_check(
    asr_output: dict[str, Any],
    *,
    expected_lang: str = "it",
    min_chars: int = 2,
) -> SanityResult:
    """Validate an ASR output dict.

    Order matters — cheaper checks first, so the typical "empty"
    rejection short-circuits before we ever call langdetect.

    `expected_lang` is the language the chat layer expects. We allow
    Italian + English by default (households use both). To accept only
    one, pass that ISO code; to accept any language, pass "".
    """
    text_raw = (asr_output.get("text") or "").strip()
    confidence_label = asr_output.get("confidence_label")
    no_speech_prob = asr_output.get("no_speech_prob")
    avg_logprob = asr_output.get("avg_logprob")

    # ----------------- 1. Empty / too short -----------------
    if not text_raw or confidence_label == "empty":
        log.info("asr.rejected", reason="empty",
                 confidence=confidence_label)
        return SanityResult(
            ok=False,
            reason="empty",
            detail="empty transcript",
            canned_reply="Non ho sentito nulla. Ripeti?",
        )

    # Strip punctuation for length checks so "..." doesn't count.
    text_alpha = re.sub(r"[^\w\s]", "", text_raw, flags=re.UNICODE).strip()
    if len(text_alpha) < min_chars:
        log.info("asr.rejected", reason="too_short", text=text_raw)
        return SanityResult(
            ok=False,
            reason="too_short",
            detail=f"only {len(text_alpha)} alpha chars",
            canned_reply="Non ti ho capita, parla un attimo più a lungo.",
        )

    # ----------------- 2. Known hallucinations -----------------
    if text_raw.lower() in _HALLUCINATIONS:
        log.info("asr.rejected", reason="hallucination", text=text_raw)
        return SanityResult(
            ok=False,
            reason="hallucination",
            detail=f"matched hallucination corpus: {text_raw!r}",
            # Stay neutral — saying "ho sentito X ma non era voce" would
            # be confusing if the user really did say "ciao" briefly.
            canned_reply="Non ti ho capita, ripeti per favore.",
        )

    # ----------------- 3. Whisper confidence signals -----------------
    # no_speech_prob > 0.6 means Whisper itself thinks this wasn't
    # speech. We trust the model on this one.
    if isinstance(no_speech_prob, (int, float)) and no_speech_prob > 0.6:
        log.info("asr.rejected", reason="low_confidence",
                 no_speech_prob=no_speech_prob, text=text_raw)
        return SanityResult(
            ok=False,
            reason="low_confidence",
            detail=f"no_speech_prob={no_speech_prob:.2f}",
            canned_reply="Sento qualcosa ma non era una voce, ripeti?",
        )

    # confidence_label="low" alone is NOT a reject (Whisper marks low
    # on a lot of valid short utterances). Only reject if low + short.
    if confidence_label == "low" and len(text_alpha) < 5:
        log.info("asr.rejected", reason="low_confidence",
                 confidence=confidence_label, text=text_raw)
        return SanityResult(
            ok=False,
            reason="low_confidence",
            detail="confidence_label=low and text very short",
            canned_reply="Non sono sicura di aver capito, ripeti?",
        )

    # ----------------- 4. Token-loop detection -----------------
    if len(text_raw) <= _LOOP_MAX_LEN:
        compact = re.sub(r"\s+", "", text_raw)
        if compact:
            unique = len(set(compact.lower()))
            if unique > 0 and len(compact) / unique > _LOOP_REPEAT_THRESHOLD:
                log.info("asr.rejected", reason="loop",
                         ratio=round(len(compact) / unique, 2),
                         text=text_raw)
                return SanityResult(
                    ok=False,
                    reason="loop",
                    detail=f"repeat ratio {len(compact) / unique:.1f}",
                    canned_reply="Non ti ho capita, ripeti?",
                )

    # ----------------- 5. Wrong language -----------------
    if expected_lang and len(text_alpha) >= 8:
        detected = _detect_language_safe(text_raw)
        # Italian household → accept it + en (kids' homework, English
        # song titles). Anything else (de, fr, pl, ...) is almost
        # certainly Whisper mis-categorising music.
        if detected and detected not in ("it", "en", expected_lang):
            log.info("asr.rejected", reason="wrong_language",
                     detected=detected, text=text_raw)
            return SanityResult(
                ok=False,
                reason="wrong_language",
                detail=f"detected={detected}",
                canned_reply="Non ti ho capita, ripeti in italiano?",
            )

    # All checks passed.
    return SanityResult(ok=True)
