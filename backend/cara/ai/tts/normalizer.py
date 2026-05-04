"""TTS text normalisation — Italian-friendly pronunciation of English loanwords.

The Piper Italian voices (paola, riccardo) read English borrowings with
Italian grapheme-to-phoneme rules — "weekend" comes out as "uéendi". This
module rewrites those words to a phonetic Italian spelling BEFORE the text
reaches Piper, so the resulting audio sounds natural to a family listener.

Two layers of substitution:

1. **Base dictionary** (`anglicisms.yaml`, ships with the project, ~300
   curated entries). Loaded once at import.
2. **User overrides** (admin panel, persisted via `set_user_overrides`).
   Win over the base dictionary, can also DELETE a base entry by mapping
   it to the empty string.

Matching is whitespace/punctuation-aware via word-boundary regex; case is
preserved on output by template (TitleCase, lowercase, UPPERCASE handled).

Designed to be CHEAP: a single compiled regex per dictionary state. Calls
to `normalize` are O(text length) and typically <1 ms for a 200-char
sentence on the NanoPC. No allocation in the steady state.

Wiring this into the TTS pipeline (one line in `tts/service.py`) is
deferred until Antonio's Step 66 lands so we don't fight the working
tree on `tts/` files.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from pathlib import Path

import structlog
import yaml


log = structlog.get_logger(__name__)


_DEFAULT_DICT_PATH = Path(__file__).resolve().parent / "anglicisms.yaml"


def _load_yaml(path: Path) -> dict[str, str]:
    """Load a {english: italian_phonetic} dict from a YAML file. Empty values strip an entry."""
    if not path.is_file():
        log.warning("tts.normalizer.dict_missing", path=str(path))
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        log.warning("tts.normalizer.dict_invalid", path=str(path))
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        if not isinstance(key, str):
            continue
        if val is None or val == "":
            continue
        if not isinstance(val, str):
            continue
        out[key.strip().lower()] = val.strip()
    return out


def _apply_case(template: str, replacement: str) -> str:
    """Mirror the casing of `template` onto `replacement` so 'WEEKEND' → 'UÌKEND'."""
    if template.isupper():
        return replacement.upper()
    if template[:1].isupper() and template[1:].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


class TTSNormalizer:
    """Text → text rewriter with hot-swappable user override layer.

    Thread-safe. Recomputing the regex after each `set_user_overrides`
    call costs a few hundred microseconds — fine because admins update
    overrides interactively, not in a hot loop.
    """

    def __init__(self, base_dict: Mapping[str, str] | None = None) -> None:
        self._base = dict(base_dict) if base_dict is not None else _load_yaml(_DEFAULT_DICT_PATH)
        self._user_overrides: dict[str, str] = {}
        self._lock = threading.Lock()
        self._regex: re.Pattern[str] | None = None
        self._effective: dict[str, str] = {}
        self._rebuild()

    # ------------------------------------------------------------------ public

    def normalize(self, text: str) -> str:
        """Return `text` with every dictionary key swapped for its mapped form.

        Empty string in, empty string out. No-op if the dictionary is empty.
        """
        if not text:
            return text
        with self._lock:
            regex = self._regex
            mapping = self._effective
        if regex is None or not mapping:
            return text

        def _sub(match: re.Match[str]) -> str:
            word = match.group(0)
            replacement = mapping.get(word.lower())
            if replacement is None:
                return word
            return _apply_case(word, replacement)

        return regex.sub(_sub, text)

    def set_user_overrides(self, overrides: Mapping[str, str]) -> None:
        """Replace the user-override layer atomically.

        Pass `{}` to clear. Empty-string values delete the corresponding
        base-dictionary entry.
        """
        cleaned: dict[str, str] = {}
        for key, val in overrides.items():
            if not isinstance(key, str):
                continue
            if not isinstance(val, str):
                continue
            cleaned[key.strip().lower()] = val.strip()
        with self._lock:
            self._user_overrides = cleaned
            self._rebuild()

    def merge_user_overrides(self, overrides: Mapping[str, str]) -> None:
        """Add/replace individual overrides without dropping the rest."""
        with self._lock:
            for key, val in overrides.items():
                if not isinstance(key, str) or not isinstance(val, str):
                    continue
                self._user_overrides[key.strip().lower()] = val.strip()
            self._rebuild()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._effective)

    def lookup(self, word: str) -> str | None:
        """Return the effective replacement for `word`, or None if unmapped."""
        with self._lock:
            return self._effective.get(word.strip().lower())

    # ----------------------------------------------------------------- internal

    def _rebuild(self) -> None:
        """Recompute the merged dictionary and the matching regex.

        Caller must hold `self._lock`.
        """
        merged = dict(self._base)
        for key, val in self._user_overrides.items():
            if val == "":
                merged.pop(key, None)
            else:
                merged[key] = val
        self._effective = merged

        if not merged:
            self._regex = None
            return
        # Sort by descending length so multi-word entries (if any) win
        # over their substrings. word boundaries `\b` handle the typical
        # case but we sort defensively.
        keys = sorted(merged.keys(), key=len, reverse=True)
        # `re.escape` so dotted keys ("vs.") would also work; alternation
        # joined with `|` and case-insensitive matching.
        pattern = r"\b(?:" + "|".join(re.escape(k) for k in keys) + r")\b"
        self._regex = re.compile(pattern, re.IGNORECASE)


# Process-level singleton for the common case. Tests should construct
# their own TTSNormalizer with explicit dicts to avoid bleeding state.
_GLOBAL: TTSNormalizer | None = None
_GLOBAL_LOCK = threading.Lock()


def get_global_normalizer() -> TTSNormalizer:
    """Return the shared default normalizer (lazily initialised)."""
    global _GLOBAL
    with _GLOBAL_LOCK:
        if _GLOBAL is None:
            _GLOBAL = TTSNormalizer()
        return _GLOBAL


def reset_global_normalizer() -> None:
    """Test helper: drop the singleton so the next call rebuilds from disk."""
    global _GLOBAL
    with _GLOBAL_LOCK:
        _GLOBAL = None
