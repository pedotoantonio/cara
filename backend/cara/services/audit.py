"""Audit log writes + reads.

All admin / privileged operations should call `record()` once they succeed.
Use a dedicated session if the caller's transaction may not commit.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models import AuditLog, User


async def record(
    session: AsyncSession,
    *,
    actor: User | None,
    action: str,
    target_kind: str | None = None,
    target_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
    note: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        target_kind=target_kind,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail,
        ip=ip,
        note=note,
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_recent(
    session: AsyncSession, *, limit: int = 100, action: str | None = None
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return list((await session.execute(stmt)).scalars().all())
