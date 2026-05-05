"""Semantic memory — extract / store / query stable facts about the family.

This is the deterministic-only first pass. It catches:

- explicit user commands  ("ricorda che…", "ricordami di…", pinned msg)
- explicit pattern matches (allergie, preferenze, abitudini ricorrenti)

Implicit / inferred extraction (a cloud LLM mining the chat history for
"facts I noticed about the user") is **deferred** until cloud is opted-
in. The Phase D code path lives behind a flag.

Two layers, in priority order:

1. EXPLICIT_PATTERNS — high-confidence regex matches that produce a
   `Fact(source="pattern", confidence=0.85)`.
2. EXPLICIT_COMMAND — "ricorda che X" / "ricordami che X" produces a
   `Fact(source="explicit", confidence=0.95)`.

Top-k retrieval uses the embedding service (Step 2.1) over the current
question, then cosine-scores against every active fact for the user.
For family-scale fact bases (<10k rows) Python-side cosine is plenty
fast; the day we cross that bar we add pgvector.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai.embeddings import EmbeddingService, top_k as topk_helper
from cara.models.fact import (
    FACT_SOURCE_EXPLICIT,
    FACT_SOURCE_PATTERN,
    FACT_TYPE_ALLERGY,
    FACT_TYPE_HABIT,
    FACT_TYPE_PERSONAL,
    FACT_TYPE_PREFERENCE,
    FACT_TYPE_SCHEDULE,
    Fact,
)


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pattern catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternHit:
    """One pattern's interpretation of a user message."""
    fact_text: str
    fact_type: str
    confidence: float
    source: str


_WEEKDAYS = (
    "lunedì",
    "martedì",
    "mercoledì",
    "giovedì",
    "venerdì",
    "sabato",
    "domenica",
)
_WEEKDAYS_RE_PART = "|".join(_WEEKDAYS)


# Pattern → builder. The builder receives the regex match and returns a
# PatternHit, or None to opt-out for this match (e.g., the captured
# group is empty after cleanup).
_PATTERN_RULES: list[tuple[re.Pattern[str], str, float]] = [
    # Explicit command — top priority.
    (
        re.compile(
            r"\bricord[a|ami]\s+(?:che|di)\s+(?P<text>.+?)(?:[.!?]|$)",
            re.IGNORECASE,
        ),
        FACT_TYPE_PERSONAL,
        0.95,
    ),

    # Allergy.
    (
        re.compile(
            r"\bsono\s+allergic[oa]\s+(?:al|allo|alla|ai|alle)\s+(?P<text>[\w\s]+?)(?:[.!?,]|$)",
            re.IGNORECASE,
        ),
        FACT_TYPE_ALLERGY,
        0.9,
    ),
    (
        re.compile(
            r"\b(?P<who>antonio|sara|marco|papà|mamma|nonna|nonno)\s+è\s+allergic[oa]\s+(?:al|allo|alla|ai|alle)\s+(?P<what>[\w\s]+?)(?:[.!?,]|$)",
            re.IGNORECASE,
        ),
        FACT_TYPE_ALLERGY,
        0.9,
    ),

    # Preference (positive / negative).
    (
        re.compile(
            r"\bnon\s+mi\s+piace\s+(?:il\s+|la\s+|i\s+|le\s+|lo\s+)?(?P<text>[\w\s]+?)(?:[.!?,]|$)",
            re.IGNORECASE,
        ),
        FACT_TYPE_PREFERENCE,
        0.85,
    ),
    (
        re.compile(
            r"\bmi\s+piace\s+(?:il\s+|la\s+|i\s+|le\s+|lo\s+)?(?P<text>[\w\s]+?)(?:[.!?,]|$)",
            re.IGNORECASE,
        ),
        FACT_TYPE_PREFERENCE,
        0.8,
    ),
    (
        re.compile(
            r"\bpreferisco\s+(?P<text>[\w\s]+?)(?:[.!?,]|$)",
            re.IGNORECASE,
        ),
        FACT_TYPE_PREFERENCE,
        0.85,
    ),

    # Schedule / habit (weekday recurrence).
    (
        re.compile(
            rf"\bogni\s+(?P<day>{_WEEKDAYS_RE_PART})\b\s+(?P<rest>.+?)(?:[.!?]|$)",
            re.IGNORECASE,
        ),
        FACT_TYPE_HABIT,
        0.85,
    ),
    (
        re.compile(
            rf"\b(?P<day>{_WEEKDAYS_RE_PART})\s+(?:di\s+|alle\s+)?(?P<rest>.+?)(?:[.!?]|$)",
            re.IGNORECASE,
        ),
        FACT_TYPE_SCHEDULE,
        0.7,
    ),
]


def detect_facts(message: str) -> list[PatternHit]:
    """Run every pattern over `message`. Returns the union of hits.

    Conservative: small message → no hits. Long messages can produce
    multiple hits (e.g. allergy + preference in the same sentence).
    """
    if not message or len(message.strip()) < 8:
        return []

    hits: list[PatternHit] = []
    seen_texts: set[str] = set()

    for pattern, fact_type, confidence in _PATTERN_RULES:
        for m in pattern.finditer(message):
            text = _build_fact_text(m, fact_type, message)
            if not text:
                continue
            normalised = text.strip().lower()
            if normalised in seen_texts:
                continue
            seen_texts.add(normalised)
            source = (
                FACT_SOURCE_EXPLICIT
                if confidence >= 0.95
                else FACT_SOURCE_PATTERN
            )
            hits.append(
                PatternHit(
                    fact_text=text.strip(),
                    fact_type=fact_type,
                    confidence=confidence,
                    source=source,
                )
            )
    return hits


def _build_fact_text(m: re.Match[str], fact_type: str, full_msg: str) -> str:
    """Produce a clean, readable fact sentence from a regex match.

    The pattern named groups vary; this helper centralises how we
    assemble a readable form so all facts read like sentences instead
    of regex captures.
    """
    groups = m.groupdict()
    text = groups.get("text", "").strip()
    if "who" in groups and "what" in groups:
        who = groups["who"].strip().capitalize()
        what = groups["what"].strip()
        return f"{who} è allergico a {what}"
    if "day" in groups:
        day = groups["day"].lower()
        rest = groups.get("rest", "").strip()
        if not rest:
            return ""
        # Avoid re-capturing chunks of the same sentence as facts:
        # keep the day → activity assertion only.
        if fact_type == FACT_TYPE_HABIT:
            return f"Ogni {day} {rest}"
        return f"{day.capitalize()}: {rest}"
    if fact_type == FACT_TYPE_PREFERENCE:
        # Positive vs negative: peek at the matched sentence.
        if " non mi piace " in (m.group(0).lower()):
            return f"Non gli piace {text}"
        return f"Gli piace {text}"
    if fact_type == FACT_TYPE_ALLERGY and "text" in groups:
        return f"È allergico a {text}"
    return text


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def save_fact(
    session: AsyncSession,
    *,
    user_id: int | None,
    text: str,
    fact_type: str,
    source: str,
    confidence: float = 1.0,
    embedding: list[float] | None = None,
    source_ref: str | None = None,
    commit: bool = False,
) -> Fact:
    """Insert a Fact row. Does NOT dedupe — the caller has more context
    about whether this is a refresh or a new piece of memory."""
    fact = Fact(
        user_id=user_id,
        type=fact_type,
        text=text,
        source=source,
        confidence=confidence,
        embedding=embedding,
        source_ref=source_ref,
    )
    session.add(fact)
    await session.flush()
    if commit:
        await session.commit()
    return fact


async def save_facts_from_message(
    session: AsyncSession,
    *,
    user_id: int | None,
    message: str,
    embedder: EmbeddingService | None = None,
    source_ref: str | None = None,
    commit: bool = False,
) -> list[Fact]:
    """Detect + persist every pattern hit in `message`.

    If `embedder` is provided, every saved fact also gets an embedding
    so it's immediately retrievable by `top_k_for_query`. Without an
    embedder the row is saved with `embedding=NULL` and an indexer job
    will fill it in later.
    """
    hits = detect_facts(message)
    if not hits:
        return []

    saved: list[Fact] = []
    embeddings: dict[str, list[float] | None] = {}
    if embedder is not None and hits:
        results = await embedder.encode_many([h.fact_text for h in hits])
        for h, r in zip(hits, results, strict=True):
            embeddings[h.fact_text] = r.vector
    for h in hits:
        saved.append(
            await save_fact(
                session,
                user_id=user_id,
                text=h.fact_text,
                fact_type=h.fact_type,
                source=h.source,
                confidence=h.confidence,
                embedding=embeddings.get(h.fact_text),
                source_ref=source_ref,
            )
        )
    if commit:
        await session.commit()
    return saved


async def list_facts(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    types: Iterable[str] | None = None,
    active_only: bool = True,
    limit: int = 100,
) -> list[Fact]:
    stmt = select(Fact).order_by(Fact.last_confirmed.desc()).limit(limit)
    if active_only:
        stmt = stmt.where(Fact.active.is_(True))
    if user_id is not None:
        stmt = stmt.where(Fact.user_id == user_id)
    if types is not None:
        types_list = list(types)
        if types_list:
            stmt = stmt.where(Fact.type.in_(types_list))
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def top_k_for_query(
    session: AsyncSession,
    *,
    query: str,
    user_id: int | None,
    embedder: EmbeddingService,
    k: int = 5,
    min_score: float = 0.5,
) -> list[tuple[Fact, float]]:
    """Cosine top-k over (active, embedding-populated) facts for `user_id`.

    Skips facts without an embedding (those will get backfilled by the
    indexer). Family-wide facts (`user_id IS NULL`) are always included.
    """
    stmt = (
        select(Fact)
        .where(Fact.active.is_(True))
        .where(Fact.embedding.is_not(None))
    )
    if user_id is not None:
        from sqlalchemy import or_

        stmt = stmt.where(or_(Fact.user_id == user_id, Fact.user_id.is_(None)))
    facts: list[Fact] = list((await session.execute(stmt)).scalars().all())
    if not facts:
        return []
    q = await embedder.encode(query)
    pairs: list[tuple[Fact, list[float]]] = [
        (f, list(f.embedding) if f.embedding else []) for f in facts if f.embedding
    ]
    return topk_helper(q.vector, pairs, k=k, min_score=min_score)


async def confirm_fact(session: AsyncSession, fact_id: int, *, commit: bool = False) -> Fact | None:
    """Bump `last_confirmed` so a re-stated fact stays fresh."""
    from sqlalchemy import update
    from datetime import datetime, timezone

    stmt = (
        update(Fact)
        .where(Fact.id == fact_id)
        .values(last_confirmed=datetime.now(timezone.utc))
        .returning(Fact)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if commit:
        await session.commit()
    return row


async def deactivate_fact(session: AsyncSession, fact_id: int, *, commit: bool = False) -> bool:
    """Mark a fact `active=False`. Used by the user "forget this" UI."""
    from sqlalchemy import update

    result = await session.execute(
        update(Fact).where(Fact.id == fact_id).values(active=False)
    )
    if commit:
        await session.commit()
    return (result.rowcount or 0) > 0
