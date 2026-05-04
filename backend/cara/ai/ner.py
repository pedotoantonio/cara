"""Italian Named Entity Recognition wrapper.

Used by:
- PII redactor (when cloud is enabled): find names/addresses/orgs in
  outgoing text so they can be replaced with placeholders.
- Semantic memory: extract entities from "ricorda che Marco è allergico
  ai pomodori" → person=Marco, food=pomodori → fact saved.
- Smart-home alias enrichment: "la lampada di Sara" → person=Sara →
  scope alias to her room.

Model: spaCy `it_core_news_lg` (~600 MB on disk, ~500 MB resident,
~50 ms per sentence on NanoPC CPU). Lazy-loaded for the same reasons
as the embedding model.

spaCy entity labels (subset CARA cares about):
  PER  → person          → "Marco", "Antonio Pedoto"
  LOC  → location        → "Roma", "via Roma 5"
  ORG  → organization    → "Google", "Conad"
  MISC → other/non-named → loose bucket; we surface but de-prioritise

We layer two extra families of detectors that spaCy's NER doesn't
natively cover well in everyday Italian:
  - regex for emails, phone numbers (IT/INT), IBAN, codice fiscale,
    P.IVA, IPv4/IPv6, URLs with query strings.
  - the family glossary (names from the users table) — overlaid on top
    of spaCy results, because spaCy occasionally misses informal
    diminutives ("Tonio" instead of "Antonio").

Tests mock spaCy so the full 600 MB model isn't required.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import structlog


log = structlog.get_logger(__name__)


_MODEL_NAME = "it_core_news_lg"

_nlp_lock = threading.Lock()
_nlp: Any | None = None


def _load_model() -> Any:
    """Lazily import spaCy and load the Italian model."""
    global _nlp
    if _nlp is not None:
        return _nlp
    with _nlp_lock:
        if _nlp is not None:
            return _nlp
        log.info("ner.loading", model=_MODEL_NAME)
        import spacy  # local import: heavy, lazy

        _nlp = spacy.load(_MODEL_NAME)
        log.info("ner.loaded", model=_MODEL_NAME)
        return _nlp


def reset_model_for_test() -> None:
    """Drop the cached pipeline so the next call reloads."""
    global _nlp
    with _nlp_lock:
        _nlp = None


# ---------------------------------------------------------------------------
# Regex detectors — fast, deterministic, complement spaCy
# ---------------------------------------------------------------------------

# Conservative on purpose: we'd rather miss a plausible-looking number
# than flag a phone number on every order quantity.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE)),
    # Italian phone: optional +39 or 0039 prefix, mobile (3xx) or landline (0xx).
    ("PHONE", re.compile(
        r"(?:(?:\+|00)39\s*)?(?:3\d{2}|0\d{1,3})[\s.\-/]?\d{3}[\s.\-/]?\d{3,4}"
    )),
    # Italian fiscal code: 6 letters + 2 digits + 1 letter + 2 digits + 1 letter + 3 digits + 1 letter
    ("CF", re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b")),
    # IBAN: country (2L) + check (2D) + bban (up to 30 alnum). IT IBANs are 27 chars.
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    # Italian VAT: 11 digits, sometimes prefixed with IT
    ("VAT", re.compile(r"\b(?:IT)?\d{11}\b")),
    # IPv4
    ("IP", re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
    )),
    # URL with explicit scheme
    ("URL", re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)),
]


@dataclass
class Entity:
    """One detected entity, with span + label + confidence."""

    text: str
    label: str            # PER | LOC | ORG | MISC | EMAIL | PHONE | CF | IBAN | VAT | IP | URL | FAMILY
    start: int
    end: int
    confidence: float = 1.0
    source: str = "spacy"   # "spacy" | "regex" | "glossary"


@dataclass
class NERResult:
    text: str
    entities: list[Entity] = field(default_factory=list)

    def by_label(self, label: str) -> list[Entity]:
        return [e for e in self.entities if e.label == label]

    @property
    def persons(self) -> list[Entity]:
        return self.by_label("PER") + self.by_label("FAMILY")

    @property
    def locations(self) -> list[Entity]:
        return self.by_label("LOC")

    @property
    def organizations(self) -> list[Entity]:
        return self.by_label("ORG")

    @property
    def has_pii(self) -> bool:
        """True if the text contains any privacy-sensitive token."""
        return any(e.label in {"EMAIL", "PHONE", "CF", "IBAN", "VAT", "IP"} for e in self.entities)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class NERService:
    """Combine spaCy NER + regex + family glossary into a unified result.

    `nlp` (the spaCy `Language` object) is injected for tests; production
    leaves it None and the singleton lazy-loaded pipeline is used.
    `family_glossary` maps a canonical name → set of aliases the user
    actually says ("Antonio Pedoto" → {"Antonio", "Tonio", "papà"}).
    """

    def __init__(
        self,
        nlp: Any | None = None,
        family_glossary: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self._nlp = nlp
        self._family_glossary = self._compile_glossary(family_glossary or {})

    @staticmethod
    def _compile_glossary(
        glossary: Mapping[str, Iterable[str]],
    ) -> list[tuple[str, re.Pattern[str]]]:
        """Pre-compile a regex per canonical name for cheap re-use."""
        out: list[tuple[str, re.Pattern[str]]] = []
        for canonical, aliases in glossary.items():
            seen = set()
            for alias in (canonical, *aliases):
                a = alias.strip()
                if a and a not in seen:
                    seen.add(a)
            if not seen:
                continue
            pattern = (
                r"\b(?:"
                + "|".join(re.escape(a) for a in sorted(seen, key=len, reverse=True))
                + r")\b"
            )
            out.append((canonical, re.compile(pattern, re.IGNORECASE)))
        return out

    def update_family_glossary(self, glossary: Mapping[str, Iterable[str]]) -> None:
        self._family_glossary = self._compile_glossary(glossary)

    def extract(self, text: str) -> NERResult:
        """Run all detectors over `text`. spaCy → regex → glossary, in that order.

        Overlapping spans are de-duplicated: if two detectors flag the
        same span, the highest-priority source wins.
        Priority: spacy > regex > glossary.
        """
        if not text:
            return NERResult(text=text)

        entities: list[Entity] = []

        # 1. spaCy
        nlp = self._nlp if self._nlp is not None else _load_model()
        try:
            doc = nlp(text)
            for ent in getattr(doc, "ents", []):
                label = self._normalise_label(getattr(ent, "label_", "MISC"))
                entities.append(
                    Entity(
                        text=str(ent.text),
                        label=label,
                        start=int(ent.start_char),
                        end=int(ent.end_char),
                        source="spacy",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("ner.spacy_failed", error=str(exc))

        # 2. Regex (PII + tech)
        for label, pattern in _PATTERNS:
            for m in pattern.finditer(text):
                entities.append(
                    Entity(
                        text=m.group(0),
                        label=label,
                        start=m.start(),
                        end=m.end(),
                        source="regex",
                    )
                )

        # 3. Family glossary
        for canonical, pattern in self._family_glossary:
            for m in pattern.finditer(text):
                entities.append(
                    Entity(
                        text=m.group(0),
                        label="FAMILY",
                        start=m.start(),
                        end=m.end(),
                        confidence=0.95,
                        source=f"glossary:{canonical}",
                    )
                )

        entities = self._dedupe_overlaps(entities)
        entities.sort(key=lambda e: e.start)
        return NERResult(text=text, entities=entities)

    @staticmethod
    def _normalise_label(label: str) -> str:
        """Normalise spaCy IT labels (PER/LOC/ORG/MISC) to our canonical set."""
        l = label.upper().strip()
        if l in {"PER", "PERSON"}:
            return "PER"
        if l in {"LOC", "GPE"}:
            return "LOC"
        if l in {"ORG"}:
            return "ORG"
        return "MISC"

    @staticmethod
    def _dedupe_overlaps(entities: list[Entity]) -> list[Entity]:
        """Drop entities whose span is contained in a higher-priority entity.

        Priority (highest first): spacy > regex > glossary.
        Reason: spaCy already understood the surrounding context, so its
        "Antonio Pedoto" beats the family glossary's "Antonio".
        """
        priority = {"spacy": 0, "regex": 1}

        def rank(e: Entity) -> int:
            for p, r in priority.items():
                if e.source.startswith(p):
                    return r
            return 2  # glossary or other

        # Sort by start asc, then by rank asc so the higher-priority entity
        # is examined first.
        sorted_ents = sorted(entities, key=lambda e: (e.start, rank(e), -(e.end - e.start)))
        kept: list[Entity] = []
        for e in sorted_ents:
            overlap = False
            for k in kept:
                if e.start < k.end and e.end > k.start:
                    if rank(e) >= rank(k):  # equal or lower priority → drop
                        overlap = True
                        break
            if not overlap:
                kept.append(e)
        return kept
