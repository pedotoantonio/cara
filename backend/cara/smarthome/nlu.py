"""Smart-home NLU — natural-language utterance → resolved action.

Critical bridge between "accendi la luce della cucina" and a precise
`call_service("light", "turn_on", "ha:light.cucina_lampada_1")`. With
50+ entities the 1.5B's tool-calling reliability isn't enough on its
own; this NLU layer is deterministic + tolerant + observable.

Resolution proceeds in four cascaded stages:

  1. **Intent regex** — does the utterance look like a smart-home
     command at all? Catches `accendi/spegni/imposta/apri/chiudi/dimmi`
     verbs and extracts the action + the target phrase + optional value.

  2. **Alias lookup** — is the target phrase a known alias of an entity?
     Aliases are auto-populated from HA `friendly_name` plus user-curated
     overrides. Exact (case-insensitive, accent-insensitive) match wins
     immediately; partial substring match scores lower.

  3. **Embedding fallback** — if alias lookup is ambiguous (no clear
     winner ≥ threshold), encode the target phrase and run cosine
     top-k against the embedded aliases. Ranks the candidates by
     semantic similarity, useful for "luce sopra il tavolo" vs
     "lampada principale cucina".

  4. **Presence disambiguation** — if multiple candidates remain after
     embedding, filter by the area where the user is currently
     standing (frigate-faces presence). One candidate left → resolve.
     More than one → prompt the user for clarification.

The resolver returns a `Resolution` carrying the chosen entity, the
action, the value, the confidence, and the path that produced it. The
chat layer uses `confidence` and `needs_clarification` to decide
whether to execute or ask first.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from cara.ai.embeddings import EmbeddingService, top_k as topk_helper
from cara.smarthome.base import Entity


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Action vocabulary
# ---------------------------------------------------------------------------


class Action(str, Enum):
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    TOGGLE = "toggle"
    SET_VALUE = "set_value"     # numeric (brightness / temperature / volume / position)
    OPEN = "open"
    CLOSE = "close"
    LOCK = "lock"
    UNLOCK = "unlock"
    QUERY = "query"             # "che temperatura c'è in cucina?"
    SCENE_ACTIVATE = "scene_activate"


# verb → Action lookup. Sorted longest-first by phrase so multi-word
# verbs ("imposta a", "metti in modalità") match before their substrings.
_INTENT_VERBS: list[tuple[re.Pattern[str], Action]] = [
    (re.compile(r"\baccendi(?:\s+(?:la|il|i|le|lo))?\b", re.IGNORECASE), Action.TURN_ON),
    (re.compile(r"\battiv[a|alo|ala]?\b", re.IGNORECASE), Action.TURN_ON),
    (re.compile(r"\b(?:spegni|disattiv[a|alo|ala])(?:\s+(?:la|il|i|le|lo))?\b", re.IGNORECASE), Action.TURN_OFF),
    (re.compile(r"\bapri(?:\s+(?:la|il|i|le|lo))?\b", re.IGNORECASE), Action.OPEN),
    (re.compile(r"\bchiudi(?:\s+(?:la|il|i|le|lo))?\b", re.IGNORECASE), Action.CLOSE),
    (re.compile(r"\b(?:imposta|metti)(?:\s+(?:la|il|lo|i|le))?\s+(?P<thing>.+?)\s+(?:a|al|alla|alle)\s+(?P<value>\S+)", re.IGNORECASE), Action.SET_VALUE),
    (re.compile(r"\bblocc(?:a|hi|halo)\b", re.IGNORECASE), Action.LOCK),
    (re.compile(r"\bsblocc(?:a|hi|halo)\b", re.IGNORECASE), Action.UNLOCK),
    (re.compile(r"\b(?:dimmi|stato di|com[ '`]è|che ne è di)\b", re.IGNORECASE), Action.QUERY),
    (re.compile(r"\battiva\s+(?:la\s+)?scen[ae]\b", re.IGNORECASE), Action.SCENE_ACTIVATE),
    (re.compile(r"\bscen[ae]\s+(?P<thing>.+)", re.IGNORECASE), Action.SCENE_ACTIVATE),
    # Toggle-style fallthrough — last resort.
    (re.compile(r"\b(?:gestisci|modifica|cambia)\b", re.IGNORECASE), Action.TOGGLE),
]


# Generic device noun → keep so "accendi la luce della cucina" → target="luce della cucina".
# We strip the leading verb + a few stop-articles and use the remainder as the target phrase.
_TRIM_PREFIXES = (
    "la ", "il ", "lo ", "i ", "le ", "gli ", "l'", "un ", "una ", "uno ",
    "del ", "della ", "dei ", "delle ", "dello ",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def _normalise(s: str) -> str:
    return _strip_accents(s.strip().lower())


def _trim_target(text: str) -> str:
    t = text.strip()
    lower = t.lower()
    for pfx in _TRIM_PREFIXES:
        if lower.startswith(pfx):
            t = t[len(pfx):].strip()
            lower = t.lower()
    return t.rstrip(".!?,;: ")


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------


@dataclass
class DeviceAlias:
    """A spoken phrase that maps to an entity, with an optional area hint."""
    entity_id: str
    alias: str
    area: str | None = None
    embedding: list[float] | None = None  # filled by `index_aliases` if embedder present
    source: str = "auto"                  # "auto" (friendly_name) | "user" | "rule"


def aliases_from_entities(entities: list[Entity]) -> list[DeviceAlias]:
    """Build the default alias list from `friendly_name` + the bare local id.

    Each entity contributes the friendly_name (lowercased) and, if
    different, a fallback alias from the local id with underscores
    converted to spaces. Hidden entities (`visible_to_cara=False`) are
    skipped.
    """
    out: list[DeviceAlias] = []
    seen: set[tuple[str, str]] = set()

    def add(entity_id: str, alias: str, area: str | None) -> None:
        norm = _normalise(alias)
        if not norm:
            return
        key = (entity_id, norm)
        if key in seen:
            return
        seen.add(key)
        out.append(DeviceAlias(entity_id=entity_id, alias=alias, area=area, source="auto"))

    for e in entities:
        if not e.visible_to_cara:
            continue
        if e.friendly_name:
            add(e.id, e.friendly_name, e.area)
        # Local id minus domain prefix as a backup alias.
        if ":" in e.id and "." in e.id:
            tail = e.id.split(":", 1)[1].split(".", 1)[1]
            spoken = tail.replace("_", " ").strip()
            if spoken and spoken.lower() != e.friendly_name.lower():
                add(e.id, spoken, e.area)
    return out


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    entity_id: str
    alias: str
    score: float
    source: str                     # "exact" | "substring" | "embedding"
    area: str | None = None


@dataclass
class Resolution:
    matched_intent: bool
    action: Action | None = None
    target_phrase: str = ""
    value: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    confidence: float = 0.0
    needs_clarification: bool = False
    reason: str = ""

    @property
    def chosen(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


_EXACT_BONUS = 1.0
_SUBSTRING_BONUS = 0.7
_EMBEDDING_FLOOR = 0.5


class SmartHomeNLU:
    """Stateless resolver: utterance + alias index → Resolution.

    Construct one per request scope (it caches the embedded alias index
    so back-to-back utterances reuse the embeddings).
    """

    def __init__(
        self,
        aliases: list[DeviceAlias],
        embedder: EmbeddingService | None = None,
        *,
        ambiguity_threshold: float = 0.05,
    ) -> None:
        self._aliases = aliases
        self._embedder = embedder
        self._ambig = ambiguity_threshold

    @property
    def aliases(self) -> list[DeviceAlias]:
        return self._aliases

    async def index_aliases(self) -> None:
        """Compute embeddings for every alias that doesn't have one yet.

        Idempotent. Skipped silently if no embedder was provided.
        """
        if self._embedder is None:
            return
        missing = [a for a in self._aliases if a.embedding is None]
        if not missing:
            return
        texts = [a.alias for a in missing]
        results = await self._embedder.encode_many(texts)
        for alias, r in zip(missing, results, strict=True):
            alias.embedding = r.vector

    # ------------------------------------------------------------------ resolve

    async def resolve(
        self,
        utterance: str,
        *,
        present_in_area: str | None = None,
    ) -> Resolution:
        intent = self._match_intent(utterance)
        if intent is None:
            return Resolution(matched_intent=False, reason="no_intent_match")

        action, target, value = intent
        target = _trim_target(target)

        candidates = self._exact_match(target)
        if not candidates:
            candidates = self._substring_match(target)

        if not candidates and self._embedder is not None:
            candidates = await self._embedding_match(target)

        # Presence-based disambiguation
        if present_in_area and len(candidates) > 1:
            in_area = [c for c in candidates if c.area and
                       _normalise(c.area) == _normalise(present_in_area)]
            if in_area:
                candidates = in_area

        candidates.sort(key=lambda c: c.score, reverse=True)

        if not candidates:
            return Resolution(
                matched_intent=True,
                action=action,
                target_phrase=target,
                value=value,
                confidence=0.0,
                needs_clarification=True,
                reason="no_candidate",
            )

        top = candidates[0]
        ambiguous = (
            len(candidates) > 1
            and (candidates[0].score - candidates[1].score) < self._ambig
        )

        return Resolution(
            matched_intent=True,
            action=action,
            target_phrase=target,
            value=value,
            candidates=candidates,
            confidence=top.score,
            needs_clarification=ambiguous,
            reason="ambiguous" if ambiguous else top.source,
        )

    # ------------------------------------------------------------ stage helpers

    def _match_intent(self, utterance: str) -> tuple[Action, str, str | None] | None:
        """Find the verb + remainder + optional value."""
        for pattern, action in _INTENT_VERBS:
            m = pattern.search(utterance)
            if not m:
                continue
            value: str | None = None
            if "value" in m.groupdict():
                value = m.group("value")
            target = ""
            if "thing" in m.groupdict():
                target = m.group("thing")
            else:
                # Take whatever comes AFTER the matched verb as the target.
                target = utterance[m.end():].strip()
                # Drop trailing words after a value indicator.
                target = re.sub(r"\s+(?:a|al|alla|alle)\s+\S+.*$", "", target)
            return action, target, value
        return None

    def _exact_match(self, target: str) -> list[Candidate]:
        norm = _normalise(target)
        if not norm:
            return []
        out: list[Candidate] = []
        for a in self._aliases:
            if _normalise(a.alias) == norm:
                out.append(Candidate(
                    entity_id=a.entity_id, alias=a.alias, score=_EXACT_BONUS,
                    source="exact", area=a.area,
                ))
        return out

    def _substring_match(self, target: str) -> list[Candidate]:
        norm = _normalise(target)
        if not norm or len(norm) < 3:
            return []
        out: list[Candidate] = []
        for a in self._aliases:
            an = _normalise(a.alias)
            if an in norm or norm in an:
                # Score reflects how much of the alias / query overlaps:
                # smaller mismatch → higher score.
                overlap = min(len(an), len(norm)) / max(len(an), len(norm))
                out.append(Candidate(
                    entity_id=a.entity_id, alias=a.alias,
                    score=_SUBSTRING_BONUS * overlap,
                    source="substring", area=a.area,
                ))
        return out

    async def _embedding_match(self, target: str) -> list[Candidate]:
        if self._embedder is None:
            return []
        # Lazy index — cheap if already done.
        await self.index_aliases()
        embedded = [a for a in self._aliases if a.embedding is not None]
        if not embedded:
            return []
        q = await self._embedder.encode(target)
        scored = topk_helper(
            q.vector,
            [(a, list(a.embedding) if a.embedding else []) for a in embedded],
            k=5, min_score=_EMBEDDING_FLOOR,
        )
        return [
            Candidate(entity_id=a.entity_id, alias=a.alias, score=score,
                      source="embedding", area=a.area)
            for a, score in scored
        ]
