"""Deterministic habit detection over the episodic event log.

Walks the last N days of `events`, buckets each row into
(user, kind, weekday, hour_bucket), and turns slots with ≥ threshold
occurrences into HabitCandidate rows. Idempotent: re-running over the
same window updates existing rows instead of duplicating them.

Confidence is `min(1.0, occurrences / 10)` — a slot seen 10+ times has
maxed-out confidence; fewer sightings drag it down. The admin reviews
candidates and accepts/rejects them — only accepted candidates feed
into proactivity rules.

This is the no-cloud baseline. A future cloud-LLM pass can produce
richer pattern descriptions ("typical task title is 'spesa per il
weekend'") on top of these slots — but that's Phase D.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.event import Event
from cara.models.habit import (
    HABIT_STATUS_ACCEPTED,
    HABIT_STATUS_DISMISSED,
    HABIT_STATUS_PENDING,
    HABIT_STATUS_REJECTED,
    HabitCandidate,
)


log = structlog.get_logger(__name__)


# Buckets: 8 three-hour slots. Easier to read in the UI than 24 hours
# and reduces noise from "I did this at 18:02 vs 18:31".
HOUR_BUCKETS = 8


def hour_to_bucket(hour: int) -> int:
    return hour // 3


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@dataclass
class DetectionResult:
    """One bucketed slot above threshold."""

    user_id: int
    kind: str
    weekday: int
    hour_bucket: int
    occurrences: int
    confidence: float
    first_seen: datetime
    last_seen: datetime
    pattern: dict[str, Any]


def detect_in_events(
    events: Iterable[Event],
    *,
    min_occurrences: int = 3,
    kinds_filter: Iterable[str] | None = None,
) -> list[DetectionResult]:
    """Pure function — given events, return slots above threshold.

    Independent of the DB, so it's trivially testable: just feed lists.
    """
    kinds_set = set(kinds_filter) if kinds_filter else None

    by_slot: dict[tuple[int, str, int, int], list[Event]] = defaultdict(list)
    for ev in events:
        if ev.user_id is None or ev.ts is None:
            continue
        if kinds_set is not None and ev.kind not in kinds_set:
            continue
        weekday = ev.ts.weekday()
        bucket = hour_to_bucket(ev.ts.hour)
        by_slot[(ev.user_id, ev.kind, weekday, bucket)].append(ev)

    results: list[DetectionResult] = []
    for (user_id, kind, weekday, bucket), slot_events in by_slot.items():
        if len(slot_events) < min_occurrences:
            continue
        slot_events.sort(key=lambda e: e.ts)
        confidence = min(1.0, len(slot_events) / 10.0)
        pattern = _summarise_pattern(slot_events)
        results.append(DetectionResult(
            user_id=user_id,
            kind=kind,
            weekday=weekday,
            hour_bucket=bucket,
            occurrences=len(slot_events),
            confidence=confidence,
            first_seen=slot_events[0].ts,
            last_seen=slot_events[-1].ts,
            pattern=pattern,
        ))
    # Stable order: highest confidence first, tie-break by occurrences.
    results.sort(key=lambda r: (r.confidence, r.occurrences), reverse=True)
    return results


def _summarise_pattern(slot_events: list[Event]) -> dict[str, Any]:
    """Build a compact summary the UI can show as 'what we noticed'.

    Pulls the most common payload keys & values for the slot. Conservative:
    only keeps keys that appear in >50% of events (otherwise it's noise).
    """
    if not slot_events:
        return {}
    n = len(slot_events)
    key_counts: Counter[str] = Counter()
    for ev in slot_events:
        for k in (ev.payload or {}).keys():
            key_counts[k] += 1
    significant = [k for k, c in key_counts.items() if c >= n * 0.5]

    pattern: dict[str, Any] = {}
    for k in significant:
        values = [ev.payload.get(k) for ev in slot_events if (ev.payload or {}).get(k) is not None]
        if not values:
            continue
        # If the value is hashable, count occurrences. Otherwise just keep
        # the most recent.
        try:
            most_common = Counter(values).most_common(1)[0][0]
            pattern[k] = most_common
        except TypeError:
            pattern[k] = values[-1]

    return pattern


# ---------------------------------------------------------------------------
# Persistence — upsert detection results into HabitCandidate rows
# ---------------------------------------------------------------------------


async def persist_detections(
    session: AsyncSession,
    results: list[DetectionResult],
    *,
    commit: bool = False,
) -> tuple[int, int]:
    """Upsert detection rows. Returns (inserted, updated).

    Idempotent: re-running over the same window updates the existing
    candidate (occurrences, last_seen, confidence) without resetting
    its admin-review status.
    """
    inserted = 0
    updated = 0

    for r in results:
        stmt = select(HabitCandidate).where(
            HabitCandidate.user_id == r.user_id,
            HabitCandidate.kind == r.kind,
            HabitCandidate.weekday == r.weekday,
            HabitCandidate.hour_bucket == r.hour_bucket,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            session.add(HabitCandidate(
                user_id=r.user_id,
                kind=r.kind,
                weekday=r.weekday,
                hour_bucket=r.hour_bucket,
                occurrences=r.occurrences,
                confidence=r.confidence,
                pattern=r.pattern,
                first_seen=r.first_seen,
                last_seen=r.last_seen,
                status=HABIT_STATUS_PENDING,
            ))
            inserted += 1
        else:
            existing.occurrences = r.occurrences
            existing.confidence = r.confidence
            existing.last_seen = r.last_seen
            existing.pattern = r.pattern
            updated += 1
    await session.flush()
    if commit:
        await session.commit()
    return inserted, updated


async def detect_and_persist(
    session: AsyncSession,
    *,
    lookback_days: int = 30,
    min_occurrences: int = 3,
    kinds_filter: Iterable[str] | None = None,
    commit: bool = False,
) -> tuple[int, int]:
    """End-to-end: read recent events, detect, upsert. Returns (ins, upd)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    stmt = select(Event).where(Event.ts >= cutoff)
    events = list((await session.execute(stmt)).scalars().all())
    detections = detect_in_events(
        events, min_occurrences=min_occurrences, kinds_filter=kinds_filter,
    )
    return await persist_detections(session, detections, commit=commit)


# ---------------------------------------------------------------------------
# Admin queue helpers
# ---------------------------------------------------------------------------


async def list_pending(
    session: AsyncSession, *, user_id: int | None = None, limit: int = 50,
) -> list[HabitCandidate]:
    stmt = (
        select(HabitCandidate)
        .where(HabitCandidate.status == HABIT_STATUS_PENDING)
        .order_by(HabitCandidate.confidence.desc(), HabitCandidate.occurrences.desc())
        .limit(limit)
    )
    if user_id is not None:
        stmt = stmt.where(HabitCandidate.user_id == user_id)
    return list((await session.execute(stmt)).scalars().all())


async def review_candidate(
    session: AsyncSession,
    candidate_id: int,
    *,
    reviewer_user_id: int,
    decision: str,                # accept|reject|dismiss
    commit: bool = False,
) -> bool:
    """Move a candidate out of the pending queue."""
    status_map = {
        "accept": HABIT_STATUS_ACCEPTED,
        "reject": HABIT_STATUS_REJECTED,
        "dismiss": HABIT_STATUS_DISMISSED,
    }
    if decision not in status_map:
        raise ValueError(f"unknown decision: {decision}")

    result = await session.execute(
        update(HabitCandidate)
        .where(HabitCandidate.id == candidate_id)
        .values(
            status=status_map[decision],
            reviewed_by=reviewer_user_id,
            reviewed_at=datetime.now(timezone.utc),
        )
    )
    if commit:
        await session.commit()
    return (result.rowcount or 0) > 0
