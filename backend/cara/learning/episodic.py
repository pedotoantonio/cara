"""Episodic memory — append-only event log persisted in Postgres.

Drop-in replacement for the in-memory ring buffer in `cara.services.event_log`:
same `record()` signature, but rows survive container restarts and are
queryable from SQL.

Usage:

    from cara.learning import episodic

    await episodic.record(
        session,
        kind="tool.call",
        user_id=user.id,
        outcome="ok",
        duration_ms=42,
        payload={"tool": "add_task", "args": {"title": "..."}},
        ref_id=conversation_id,
    )

The session is passed in (not opened internally) so callers control
transaction scope. A fire-and-forget helper (`record_async`) is provided for
the common case where the caller doesn't have a session at hand.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.event import Event
from cara.store.db import get_sessionmaker


log = structlog.get_logger(__name__)


# Maximum payload size we'll persist. Anything bigger gets truncated with a
# marker — episodic rows shouldn't accumulate megabytes.
_MAX_PAYLOAD_BYTES = 16_000


def _truncate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitise + size-cap a payload before persisting.

    Two jobs:
      1. Round-trip through `json.dumps(default=str) → json.loads` so the
         dict only contains JSON-native types. SQLAlchemy will serialise
         it later WITHOUT `default=str`, so any non-serialisable object
         that slips through here would crash the insert.
      2. Cap byte size: anything over `_MAX_PAYLOAD_BYTES` becomes a
         marker dict with a preview. Episodic rows shouldn't accumulate
         megabytes.
    """
    import json

    try:
        raw = json.dumps(payload, default=str)
        clean = json.loads(raw)
    except (TypeError, ValueError):
        # Truly unserialisable (e.g. circular refs default=str doesn't help with).
        return {"_truncated": True, "_reason": "non_json_serialisable"}
    if len(raw) <= _MAX_PAYLOAD_BYTES:
        return clean
    return {
        "_truncated": True,
        "_original_bytes": len(raw),
        "_preview": raw[:1000],
    }


async def record(
    session: AsyncSession,
    *,
    kind: str,
    user_id: int | None = None,
    outcome: str | None = None,
    duration_ms: int | float | None = None,
    payload: dict[str, Any] | None = None,
    ref_id: str | None = None,
    commit: bool = False,
) -> Event:
    """Persist a single event row.

    `commit` defaults to False so the caller keeps transactional control. Set
    it True for fire-and-forget calls outside an existing transaction.
    """
    event = Event(
        kind=kind,
        user_id=user_id,
        outcome=outcome,
        duration_ms=int(duration_ms) if duration_ms is not None else None,
        payload=_truncate_payload(payload or {}),
        ref_id=ref_id,
    )
    session.add(event)
    await session.flush()  # populate id/ts so callers can read them
    if commit:
        await session.commit()
    return event


async def record_async(
    *,
    kind: str,
    user_id: int | None = None,
    outcome: str | None = None,
    duration_ms: int | float | None = None,
    payload: dict[str, Any] | None = None,
    ref_id: str | None = None,
) -> None:
    """Fire-and-forget record from contexts that don't already have a session.

    Opens its own session, writes, commits, closes. Errors are logged but
    swallowed: episodic.record_async must NEVER bring down the caller's
    request path.
    """
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            await record(
                session,
                kind=kind,
                user_id=user_id,
                outcome=outcome,
                duration_ms=duration_ms,
                payload=payload,
                ref_id=ref_id,
                commit=True,
            )
    except Exception as exc:  # noqa: BLE001 — fire-and-forget by design
        log.warning("episodic.record_async.failed", kind=kind, error=str(exc))


async def query(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    kinds: Iterable[str] | None = None,
    ref_id: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[Event]:
    """Newest-first query with the most useful filters baked in.

    `kinds` is matched as exact `IN (...)`. For prefix wildcard ("tool.%")
    callers should use the SQLAlchemy session directly — this helper stays
    deliberately simple.
    """
    stmt = select(Event).order_by(Event.ts.desc())
    if user_id is not None:
        stmt = stmt.where(Event.user_id == user_id)
    if kinds is not None:
        kind_list = list(kinds)
        if kind_list:
            stmt = stmt.where(Event.kind.in_(kind_list))
    if ref_id is not None:
        stmt = stmt.where(Event.ref_id == ref_id)
    if since is not None:
        stmt = stmt.where(Event.ts >= since)
    stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def cleanup_old(
    session: AsyncSession,
    *,
    retention_days: int = 90,
    commit: bool = True,
) -> int:
    """Delete events older than `retention_days`. Returns rows removed.

    Cheap enough to run as a daily cron. The `events_user_ts` index lets
    Postgres pick rows efficiently if retention runs often; for very large
    tables consider partitioning by month later.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    stmt = delete(Event).where(Event.ts < cutoff)
    result = await session.execute(stmt)
    removed = result.rowcount or 0
    if commit:
        await session.commit()
    if removed:
        log.info("episodic.cleanup", removed=removed, cutoff=cutoff.isoformat())
    return removed
