"""Unit tests for `cara.learning.habits` — habit detection + persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cara.learning import episodic, habits
from cara.learning.habits import (
    DetectionResult,
    detect_in_events,
    hour_to_bucket,
)
from cara.models.event import Event
from cara.models.habit import (
    HABIT_STATUS_ACCEPTED,
    HABIT_STATUS_REJECTED,
    HabitCandidate,
)


pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------- helpers


async def _seed_user(db_session, uid: int):
    from cara.models.user import User

    u = User(id=uid, email=f"u{uid}@example.com", password_hash="x",
             full_name=None, is_admin=False, is_active=True, role="parent")
    db_session.add(u)
    await db_session.flush()
    return u


def _evt(user_id: int, kind: str, dt: datetime, payload=None) -> Event:
    """Build an Event without persisting it (pure in-memory)."""
    return Event(
        user_id=user_id, kind=kind, ts=dt, payload=payload or {},
    )


# --------------------------------------------------------------- hour_to_bucket


def test_hour_to_bucket_3h_buckets() -> None:
    assert hour_to_bucket(0) == 0
    assert hour_to_bucket(2) == 0
    assert hour_to_bucket(3) == 1
    assert hour_to_bucket(11) == 3
    assert hour_to_bucket(18) == 6
    assert hour_to_bucket(23) == 7


# --------------------------------------------------------------- detect_in_events


def test_detect_returns_empty_when_no_events() -> None:
    assert detect_in_events([]) == []


def test_detect_below_threshold_yields_nothing() -> None:
    events = [
        _evt(1, "task.created",
             datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)),
        _evt(1, "task.created",
             datetime(2026, 5, 11, 18, 0, tzinfo=timezone.utc)),
    ]
    out = detect_in_events(events, min_occurrences=3)
    assert out == []


def test_detect_above_threshold_returns_slot() -> None:
    """Same user, kind, weekday + hour bucket appearing 3+ times."""
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)  # a Monday
    events = [
        _evt(1, "task.created", base),
        _evt(1, "task.created", base + timedelta(days=7)),
        _evt(1, "task.created", base + timedelta(days=14)),
    ]
    out = detect_in_events(events, min_occurrences=3)
    assert len(out) == 1
    r = out[0]
    assert isinstance(r, DetectionResult)
    assert r.user_id == 1
    assert r.kind == "task.created"
    assert r.weekday == 0  # Monday
    assert r.hour_bucket == 6  # 18-21
    assert r.occurrences == 3
    assert r.confidence == pytest.approx(0.3)
    assert r.first_seen == base
    assert r.last_seen == base + timedelta(days=14)


def test_detect_skips_events_with_no_user_id() -> None:
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    events = [
        _evt(None, "task.created", base + timedelta(days=i * 7))
        for i in range(5)
    ]
    out = detect_in_events(events, min_occurrences=3)
    assert out == []


def test_detect_kinds_filter() -> None:
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    events = [
        _evt(1, "task.created", base + timedelta(days=i * 7)) for i in range(3)
    ] + [
        _evt(1, "shopping.add", base + timedelta(days=i * 7)) for i in range(3)
    ]
    out = detect_in_events(events, kinds_filter={"task.created"}, min_occurrences=3)
    assert len(out) == 1
    assert out[0].kind == "task.created"


def test_detect_confidence_caps_at_one() -> None:
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    events = [
        _evt(1, "task.created", base + timedelta(days=i * 7)) for i in range(15)
    ]
    out = detect_in_events(events, min_occurrences=3)
    assert out[0].confidence == 1.0


def test_detect_pattern_summary_keeps_significant_keys() -> None:
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    # `category` consistent across 4/5 → kept. `note` random → dropped.
    events = [
        _evt(1, "task.created", base + timedelta(days=0),
             payload={"category": "spesa", "note": "n1"}),
        _evt(1, "task.created", base + timedelta(days=7),
             payload={"category": "spesa"}),
        _evt(1, "task.created", base + timedelta(days=14),
             payload={"category": "spesa"}),
        _evt(1, "task.created", base + timedelta(days=21),
             payload={"category": "lavoro"}),  # outlier on category
        _evt(1, "task.created", base + timedelta(days=28),
             payload={"category": "spesa"}),
    ]
    [r] = detect_in_events(events, min_occurrences=3)
    assert r.pattern.get("category") == "spesa"  # most common value


def test_detect_results_sorted_by_confidence_desc() -> None:
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    # Two slots; "task.created" 5 times, "shopping.add" 3 times.
    events = [
        _evt(1, "task.created", base + timedelta(days=i * 7)) for i in range(5)
    ] + [
        _evt(1, "shopping.add", base + timedelta(days=i * 7)) for i in range(3)
    ]
    out = detect_in_events(events, min_occurrences=3)
    assert len(out) == 2
    assert out[0].kind == "task.created"  # higher confidence first


# --------------------------------------------------------------- persistence


async def test_persist_detections_inserts_new_rows(db_session) -> None:
    await _seed_user(db_session, 1)
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    detections = [
        DetectionResult(
            user_id=1, kind="task.created", weekday=0, hour_bucket=6,
            occurrences=3, confidence=0.3,
            first_seen=base, last_seen=base + timedelta(days=14),
            pattern={},
        ),
    ]
    inserted, updated = await habits.persist_detections(
        db_session, detections, commit=True,
    )
    assert inserted == 1
    assert updated == 0


async def test_persist_detections_idempotent_updates_existing(db_session) -> None:
    await _seed_user(db_session, 1)
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    det1 = DetectionResult(
        user_id=1, kind="task.created", weekday=0, hour_bucket=6,
        occurrences=3, confidence=0.3,
        first_seen=base, last_seen=base + timedelta(days=14), pattern={},
    )
    await habits.persist_detections(db_session, [det1], commit=True)

    # Same slot, occurrences bumped to 5.
    det2 = DetectionResult(
        user_id=1, kind="task.created", weekday=0, hour_bucket=6,
        occurrences=5, confidence=0.5,
        first_seen=base, last_seen=base + timedelta(days=28),
        pattern={"category": "spesa"},
    )
    inserted, updated = await habits.persist_detections(
        db_session, [det2], commit=True,
    )
    assert inserted == 0
    assert updated == 1

    from sqlalchemy import select
    candidate = (await db_session.execute(
        select(HabitCandidate).where(HabitCandidate.user_id == 1)
    )).scalar_one()
    assert candidate.occurrences == 5
    assert candidate.confidence == pytest.approx(0.5)
    assert candidate.pattern == {"category": "spesa"}


async def test_detect_and_persist_end_to_end(db_session) -> None:
    """Seed events, run the full detect + persist pipeline."""
    await _seed_user(db_session, 1)
    base = datetime.now(timezone.utc) - timedelta(days=21)
    for i in range(3):
        await episodic.record(
            db_session, kind="task.created", user_id=1,
            payload={"category": "spesa"},
        )
    # Backdate manually so they all sit in the same weekday/hour bucket.
    from sqlalchemy import update
    await db_session.execute(
        update(Event).where(Event.user_id == 1).values(ts=base.replace(
            hour=18, minute=0, second=0, microsecond=0,
        ))
    )
    # Spread them over weekly intervals to mimic "every Tuesday".
    rows = list((await db_session.execute(
        __import__("sqlalchemy").select(Event)
    )).scalars().all())
    for i, ev in enumerate(rows):
        ev.ts = base + timedelta(days=i * 7)
    await db_session.commit()

    inserted, updated = await habits.detect_and_persist(
        db_session, lookback_days=60, min_occurrences=3, commit=True,
    )
    assert inserted == 1


async def test_list_pending_returns_only_pending(db_session) -> None:
    await _seed_user(db_session, 1)
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)

    db_session.add(HabitCandidate(
        user_id=1, kind="x", weekday=0, hour_bucket=6,
        occurrences=3, confidence=0.3, first_seen=base, last_seen=base,
        pattern={}, status="pending",
    ))
    db_session.add(HabitCandidate(
        user_id=1, kind="y", weekday=0, hour_bucket=6,
        occurrences=3, confidence=0.3, first_seen=base, last_seen=base,
        pattern={}, status=HABIT_STATUS_ACCEPTED,
    ))
    await db_session.commit()

    pending = await habits.list_pending(db_session, user_id=1)
    kinds = {c.kind for c in pending}
    assert kinds == {"x"}


async def test_review_candidate_accept(db_session) -> None:
    await _seed_user(db_session, 1)
    await _seed_user(db_session, 2)  # reviewer
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    cand = HabitCandidate(
        user_id=1, kind="x", weekday=0, hour_bucket=6,
        occurrences=3, confidence=0.3, first_seen=base, last_seen=base,
        pattern={}, status="pending",
    )
    db_session.add(cand)
    await db_session.commit()

    ok = await habits.review_candidate(
        db_session, cand.id, reviewer_user_id=2, decision="accept", commit=True,
    )
    assert ok is True
    await db_session.refresh(cand)
    assert cand.status == HABIT_STATUS_ACCEPTED
    assert cand.reviewed_by == 2


async def test_review_candidate_reject_records_status(db_session) -> None:
    await _seed_user(db_session, 1)
    base = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    cand = HabitCandidate(
        user_id=1, kind="x", weekday=0, hour_bucket=6,
        occurrences=3, confidence=0.3, first_seen=base, last_seen=base,
        pattern={}, status="pending",
    )
    db_session.add(cand)
    await db_session.commit()

    await habits.review_candidate(
        db_session, cand.id, reviewer_user_id=1, decision="reject", commit=True,
    )
    await db_session.refresh(cand)
    assert cand.status == HABIT_STATUS_REJECTED


async def test_review_candidate_unknown_decision_raises(db_session) -> None:
    with pytest.raises(ValueError, match="unknown decision"):
        await habits.review_candidate(
            db_session, candidate_id=1, reviewer_user_id=1,
            decision="approve_maybe", commit=False,
        )


async def test_review_candidate_unknown_id_returns_false(db_session) -> None:
    ok = await habits.review_candidate(
        db_session, candidate_id=99999, reviewer_user_id=1,
        decision="accept", commit=True,
    )
    assert ok is False
