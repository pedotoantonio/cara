"""Unit tests for `cara.learning.episodic` — episodic memory CRUD/query.

In-memory SQLite, no backend running, fast.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cara.learning import episodic
from cara.models.event import Event


pytestmark = pytest.mark.asyncio


async def test_record_persists_with_defaults(db_session) -> None:
    ev = await episodic.record(
        db_session,
        kind="chat.turn",
        payload={"text": "ciao"},
    )
    assert ev.id is not None
    assert ev.kind == "chat.turn"
    assert ev.payload == {"text": "ciao"}
    assert ev.outcome is None
    assert ev.duration_ms is None
    # ts is server-default in Postgres; in SQLite the func.now() default
    # still fires, so it should be set.
    assert ev.ts is not None


async def test_record_with_full_metadata(db_session) -> None:
    ev = await episodic.record(
        db_session,
        kind="tool.call",
        user_id=None,  # FK SET NULL behaviour, no users table seeded
        outcome="ok",
        duration_ms=42.7,
        payload={"tool": "add_task", "args": {"title": "spesa"}},
        ref_id="conv-abc",
    )
    assert ev.outcome == "ok"
    assert ev.duration_ms == 42  # int-coerced
    assert ev.ref_id == "conv-abc"


async def test_record_truncates_huge_payload(db_session) -> None:
    big = {"blob": "x" * 50_000}
    ev = await episodic.record(db_session, kind="tool.call", payload=big)
    assert ev.payload.get("_truncated") is True
    assert ev.payload.get("_original_bytes", 0) > 16_000


async def test_record_handles_unserialisable_payload(db_session) -> None:
    # SQLAlchemy / asyncpg can't store an arbitrary Python object directly,
    # so we substitute a marker dict before persisting.
    class WeirdObject:
        pass

    ev = await episodic.record(
        db_session,
        kind="tool.call",
        payload={"obj": WeirdObject()},  # type: ignore[dict-item]
    )
    # Accept either: stringified via default=str (small enough to keep)
    # OR the truncation marker. Both are valid behaviours.
    assert "_truncated" in ev.payload or "obj" in ev.payload


async def _seed_user(db_session, user_id: int, email: str):
    """Insert a minimal valid User row so FK references hold."""
    from cara.models.user import User

    user = User(
        id=user_id,
        email=email,
        password_hash="x",
        full_name=None,
        is_admin=False,
        is_active=True,
        role="parent",
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_query_filters_by_user_kind_and_ref(db_session) -> None:
    await _seed_user(db_session, 1, "u1@example.com")
    await _seed_user(db_session, 2, "u2@example.com")

    await episodic.record(db_session, kind="chat.turn", user_id=1, ref_id="conv-1")
    await episodic.record(db_session, kind="chat.turn", user_id=2, ref_id="conv-2")
    await episodic.record(db_session, kind="tool.call", user_id=1, ref_id="conv-1")
    await db_session.commit()

    user1 = await episodic.query(db_session, user_id=1)
    assert len(user1) == 2

    chat_only = await episodic.query(db_session, kinds=["chat.turn"])
    assert len(chat_only) == 2
    assert all(e.kind == "chat.turn" for e in chat_only)

    conv1 = await episodic.query(db_session, ref_id="conv-1")
    assert len(conv1) == 2

    # Newest-first ordering
    timestamps = [e.ts for e in await episodic.query(db_session, limit=10)]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_query_respects_limit(db_session) -> None:
    for i in range(10):
        await episodic.record(db_session, kind="chat.turn", payload={"i": i})
    await db_session.commit()

    rows = await episodic.query(db_session, limit=3)
    assert len(rows) == 3


async def test_query_since_drops_old_rows(db_session) -> None:
    old = await episodic.record(db_session, kind="chat.turn")
    # Backdate manually — server_default already set ts to now()
    old.ts = datetime.now(timezone.utc) - timedelta(days=10)
    await episodic.record(db_session, kind="chat.turn")
    await db_session.commit()

    recent = await episodic.query(
        db_session, since=datetime.now(timezone.utc) - timedelta(days=1)
    )
    assert len(recent) == 1


async def test_cleanup_old_removes_only_old_rows(db_session) -> None:
    # Two old, one recent.
    for _ in range(2):
        ev = await episodic.record(db_session, kind="chat.turn")
        ev.ts = datetime.now(timezone.utc) - timedelta(days=120)
    await episodic.record(db_session, kind="chat.turn")
    await db_session.commit()

    removed = await episodic.cleanup_old(db_session, retention_days=90)
    assert removed == 2

    remaining = (await db_session.execute(__import__("sqlalchemy").select(Event))).scalars().all()
    assert len(list(remaining)) == 1


async def test_cleanup_old_returns_zero_when_nothing_to_remove(db_session) -> None:
    await episodic.record(db_session, kind="chat.turn")
    await db_session.commit()
    removed = await episodic.cleanup_old(db_session, retention_days=90)
    assert removed == 0
