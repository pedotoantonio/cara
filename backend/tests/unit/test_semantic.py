"""Unit tests for `cara.learning.semantic` — pattern detection + persistence."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cara.ai.embeddings import EmbeddingService
from cara.learning import semantic
from cara.models.fact import (
    FACT_SOURCE_EXPLICIT,
    FACT_SOURCE_PATTERN,
    FACT_TYPE_ALLERGY,
    FACT_TYPE_HABIT,
    FACT_TYPE_PERSONAL,
    FACT_TYPE_PREFERENCE,
)


pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------- pattern detection (sync)


def test_detect_explicit_command() -> None:
    hits = semantic.detect_facts("ricorda che a Marco non piacciono le melanzane.")
    assert hits, "explicit 'ricorda che' must produce at least one hit"
    explicit = [h for h in hits if h.source == FACT_SOURCE_EXPLICIT]
    assert explicit, "explicit hit should be classified as 'explicit' source"


def test_detect_allergy_first_person() -> None:
    hits = semantic.detect_facts("sono allergico ai pomodori.")
    types = {h.fact_type for h in hits}
    assert FACT_TYPE_ALLERGY in types


def test_detect_allergy_third_person_with_named_member() -> None:
    hits = semantic.detect_facts("Marco è allergico alle arachidi.")
    types = {h.fact_type for h in hits}
    assert FACT_TYPE_ALLERGY in types
    # The text is reformulated as a sentence with the subject preserved.
    assert any("Marco" in h.fact_text for h in hits if h.fact_type == FACT_TYPE_ALLERGY)


def test_detect_preference_negative() -> None:
    hits = semantic.detect_facts("Non mi piace la pasta al sugo.")
    pref = [h for h in hits if h.fact_type == FACT_TYPE_PREFERENCE]
    assert pref


def test_detect_preference_positive() -> None:
    hits = semantic.detect_facts("Mi piace il caffè.")
    pref = [h for h in hits if h.fact_type == FACT_TYPE_PREFERENCE]
    assert pref


def test_detect_habit_weekday() -> None:
    hits = semantic.detect_facts("Ogni martedì Marco ha allenamento.")
    habits = [h for h in hits if h.fact_type == FACT_TYPE_HABIT]
    assert habits


def test_detect_no_facts_in_short_message() -> None:
    """Conservative: very short messages don't trigger anything."""
    assert semantic.detect_facts("ciao") == []


def test_detect_dedupes_same_normalised_text() -> None:
    """A message that the same regex matches twice produces only one hit."""
    hits = semantic.detect_facts(
        "sono allergico ai pomodori. Sono allergico ai pomodori, davvero."
    )
    allergies = [h for h in hits if h.fact_type == FACT_TYPE_ALLERGY]
    # Both occurrences collapse to one normalised hit.
    assert len(allergies) == 1


# --------------------------------------------------------------- persistence


async def _seed_user(db_session, uid: int):
    from cara.models.user import User

    u = User(id=uid, email=f"u{uid}@example.com", password_hash="x",
             full_name=None, is_admin=False, is_active=True, role="parent")
    db_session.add(u)
    await db_session.flush()
    return u


async def test_save_fact_persists_row(db_session) -> None:
    await _seed_user(db_session, 1)
    f = await semantic.save_fact(
        db_session, user_id=1, text="È allergico ai pomodori",
        fact_type=FACT_TYPE_ALLERGY, source=FACT_SOURCE_PATTERN, confidence=0.9,
    )
    assert f.id is not None
    assert f.active is True


async def test_save_facts_from_message_inserts_each_hit(db_session) -> None:
    await _seed_user(db_session, 1)
    saved = await semantic.save_facts_from_message(
        db_session, user_id=1,
        message="Sono allergico ai pomodori. Mi piace il caffè.",
    )
    assert len(saved) >= 2
    types = {f.type for f in saved}
    assert FACT_TYPE_ALLERGY in types
    assert FACT_TYPE_PREFERENCE in types


async def test_save_facts_from_message_with_embedder_attaches_vectors(db_session) -> None:
    await _seed_user(db_session, 1)
    # Fake embedder that returns a unique 3-d vector per text.
    fake_model = MagicMock()
    fake_model.encode = MagicMock(side_effect=lambda texts, **_kw:
                                  [[float(i), 0.0, 0.0] for i, _ in enumerate(texts)])
    embedder = EmbeddingService(model=fake_model, dim=3)

    saved = await semantic.save_facts_from_message(
        db_session, user_id=1,
        message="Sono allergico ai pomodori.",
        embedder=embedder,
    )
    assert saved
    assert all(f.embedding for f in saved)


async def test_save_facts_from_message_no_pattern_no_rows(db_session) -> None:
    """Nothing detected → nothing persisted."""
    await _seed_user(db_session, 1)
    saved = await semantic.save_facts_from_message(
        db_session, user_id=1, message="ciao",
    )
    assert saved == []


async def test_list_facts_returns_user_facts_active_only(db_session) -> None:
    await _seed_user(db_session, 1)
    f1 = await semantic.save_fact(
        db_session, user_id=1, text="A", fact_type=FACT_TYPE_PERSONAL,
        source=FACT_SOURCE_EXPLICIT,
    )
    f2 = await semantic.save_fact(
        db_session, user_id=1, text="B", fact_type=FACT_TYPE_PERSONAL,
        source=FACT_SOURCE_EXPLICIT,
    )
    # Deactivate one
    await semantic.deactivate_fact(db_session, f2.id)
    await db_session.commit()

    out = await semantic.list_facts(db_session, user_id=1)
    ids = [f.id for f in out]
    assert f1.id in ids
    assert f2.id not in ids


async def test_top_k_for_query_returns_only_embedded_facts(db_session) -> None:
    await _seed_user(db_session, 1)
    # Two facts: one with embedding, one without.
    embedded = await semantic.save_fact(
        db_session, user_id=1, text="È allergico ai pomodori",
        fact_type=FACT_TYPE_ALLERGY, source=FACT_SOURCE_PATTERN,
        embedding=[1.0, 0.0, 0.0],
    )
    await semantic.save_fact(
        db_session, user_id=1, text="non rilevante",
        fact_type=FACT_TYPE_PERSONAL, source=FACT_SOURCE_EXPLICIT,
        # no embedding → must be excluded
    )
    await db_session.commit()

    fake_model = MagicMock()
    # Query embedding identical to `embedded.embedding` → score 1.0.
    fake_model.encode = MagicMock(return_value=[[1.0, 0.0, 0.0]])
    embedder = EmbeddingService(model=fake_model, dim=3)

    pairs = await semantic.top_k_for_query(
        db_session, query="posso mangiare la pizza?", user_id=1,
        embedder=embedder, k=3, min_score=0.5,
    )
    assert len(pairs) == 1
    fact, score = pairs[0]
    assert fact.id == embedded.id
    assert score >= 0.99


async def test_top_k_includes_family_wide_facts(db_session) -> None:
    """user_id=NULL facts are visible to every family member's query."""
    await _seed_user(db_session, 1)
    family = await semantic.save_fact(
        db_session, user_id=None, text="Casa Pedoto cena alle 20",
        fact_type=FACT_TYPE_HABIT, source=FACT_SOURCE_EXPLICIT,
        embedding=[1.0, 0.0, 0.0],
    )
    await db_session.commit()

    fake_model = MagicMock()
    fake_model.encode = MagicMock(return_value=[[1.0, 0.0, 0.0]])
    embedder = EmbeddingService(model=fake_model, dim=3)

    out = await semantic.top_k_for_query(
        db_session, query="a che ora si cena?", user_id=1,
        embedder=embedder, k=5, min_score=0.5,
    )
    assert any(f.id == family.id for f, _ in out)


async def test_confirm_fact_returns_the_row(db_session) -> None:
    """confirm_fact returns the updated row when the id exists.

    We don't assert ts ordering here because SQLite stores naive datetimes
    while server-default `now()` round-tripping is dialect-specific.
    What matters: the row is returned (= update hit).
    """
    await _seed_user(db_session, 1)
    f = await semantic.save_fact(
        db_session, user_id=1, text="x",
        fact_type=FACT_TYPE_PERSONAL, source=FACT_SOURCE_EXPLICIT,
    )
    await db_session.commit()
    bumped = await semantic.confirm_fact(db_session, f.id, commit=True)
    assert bumped is not None
    assert bumped.id == f.id


async def test_confirm_fact_returns_none_for_unknown_id(db_session) -> None:
    out = await semantic.confirm_fact(db_session, fact_id=99999, commit=True)
    assert out is None


async def test_deactivate_fact_returns_true_on_hit(db_session) -> None:
    await _seed_user(db_session, 1)
    f = await semantic.save_fact(
        db_session, user_id=1, text="x",
        fact_type=FACT_TYPE_PERSONAL, source=FACT_SOURCE_EXPLICIT,
    )
    await db_session.commit()
    ok = await semantic.deactivate_fact(db_session, f.id, commit=True)
    assert ok is True


async def test_deactivate_fact_returns_false_on_unknown_id(db_session) -> None:
    ok = await semantic.deactivate_fact(db_session, fact_id=99999, commit=True)
    assert ok is False
