"""Task (to-do) persistence helpers — scoped per user."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models import Task


async def list_tasks(
    session: AsyncSession, *, user_id: int, include_done: bool = True
) -> list[Task]:
    stmt = select(Task).where(Task.user_id == user_id)
    if not include_done:
        stmt = stmt.where(Task.done.is_(False))
    # Order: pending first, then by due_date asc (NULLs last via coalesce trick),
    # then most recent. Pending overdue tasks naturally bubble to the top.
    stmt = stmt.order_by(
        Task.done.asc(),
        Task.due_date.asc().nullslast(),
        Task.created_at.desc(),
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_task(
    session: AsyncSession,
    *,
    user_id: int,
    title: str,
    due_date: datetime | None = None,
) -> Task:
    task = Task(user_id=user_id, title=title, due_date=due_date)
    session.add(task)
    await session.flush()
    return task


async def get_task(
    session: AsyncSession, task_id: uuid.UUID, *, user_id: int
) -> Task | None:
    stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    return (await session.execute(stmt)).scalar_one_or_none()


_UNSET: object = object()


async def update_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    user_id: int,
    title: str | None = None,
    done: bool | None = None,
    due_date: datetime | None | object = _UNSET,
) -> Task | None:
    task = await get_task(session, task_id, user_id=user_id)
    if task is None:
        return None
    if title is not None:
        task.title = title
    if done is not None and done != task.done:
        task.done = done
        task.completed_at = datetime.now(UTC) if done else None
    if due_date is not _UNSET:
        task.due_date = due_date  # type: ignore[assignment]
    await session.flush()
    return task


async def delete_task(
    session: AsyncSession, task_id: uuid.UUID, *, user_id: int
) -> bool:
    task = await get_task(session, task_id, user_id=user_id)
    if task is None:
        return False
    await session.delete(task)
    return True
