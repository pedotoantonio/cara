"""Grounding/discover heuristics extracted from `chat.py`.

Three pure functions used by the chat hot path to decide whether a user
question needs CDA grounding (we run discover server-side and re-prompt
the LLM with the article injected) and which `kind` of CDA discovery to
ask for:

- `needs_grounding(question)` — regex over knowledge-need patterns.
- `infer_kind(question)` — "podcast" / "audio_stream" / "video" / "image" /
  default "article".
- `has_discover_tool(text)` — best-effort detection of the model emitting
  a `discover` tool call (tolerant of TOOL/TUPO/TWOOL/TU prefix typos
  the 1.5B often makes).
"""

from __future__ import annotations

import re


# Patterns that suggest the user is asking for a fact the LLM is likely
# to hallucinate. Conservative — too many entries means we round-trip
# CDA on every chat turn; too few means hallucinations slip through.
_GROUND_PATTERNS = [
    r"\bcos[a']?\s*[èe']\b",            # cos'è, cosa è
    r"\bchi\s*[èe]\b",                   # chi è
    r"\bdove\s+(?:[èe]|si\s+trova)\b",
    r"\bquando\s+(?:[èe]|sarà|è\s+stato)\b",
    r"\bspiegami\b",
    r"\bdefinisci\b",
    r"\bche\s+(?:vuol\s+dire|significa)\b",
    r"\bdimmi\s+(?:cosa|chi|dove|quando)\b",
    r"\bmeteo\b",
    r"\bprevisioni\b",
    r"\bvincitore\b",
    r"\bquanto\s+costa\b",
    r"\bin\s+che\s+anno\b",
    r"\bha\s+vinto\b",
    r"\bè\s+vero\s+che\b",
]
_GROUND_RE = re.compile("|".join(_GROUND_PATTERNS), re.IGNORECASE)


def needs_grounding(question: str) -> bool:
    """True if the user's question likely needs grounded information."""
    return bool(_GROUND_RE.search(question or ""))


def infer_kind(question: str) -> str:
    """Cheap classifier: pick the right `kind` for discover from the question."""
    q = (question or "").lower()
    if re.search(r"\b(podcast|puntata)\b", q):
        return "podcast"
    if re.search(r"\b(ascolta|ascoltare|radio|musica)\b", q):
        return "audio_stream"
    if re.search(r"\b(video|trailer|guarda)\b", q):
        return "video"
    if re.search(r"\b(foto|immagine|immagini)\b", q):
        return "image"
    return "article"


def has_discover_tool(text: str) -> bool:
    """Best-effort detection of the model emitting any `discover` tool call,
    tolerant of the 1.5B's typical typos (TOOL/TUPO/TWOOL/TU prefix)."""
    return bool(re.search(r"\[\s*[A-Z_]*\s*:?\s*discover\b", text, flags=re.IGNORECASE))
