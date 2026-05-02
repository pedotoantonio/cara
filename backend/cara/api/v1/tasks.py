"""Task (to-do) CRUD endpoints — auth-required, user-scoped."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.schemas.task import TaskCreate, TaskOut, TaskUpdate
from cara.services import tasks as svc
from cara.store import get_session

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    include_done: bool = True,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[TaskOut]:
    rows = await svc.list_tasks(session, user_id=user.id, include_done=include_done)
    return [TaskOut.model_validate(r) for r in rows]


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TaskOut:
    task = await svc.create_task(
        session, user_id=user.id, title=body.title, due_date=body.due_date
    )
    return TaskOut.model_validate(task)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TaskOut:
    # PATCH semantics: only fields present in the request body are touched.
    # Pydantic v2: `model_fields_set` tells us which keys came from JSON.
    kwargs: dict = {"title": body.title, "done": body.done}
    if "due_date" in body.model_fields_set:
        kwargs["due_date"] = body.due_date
    task = await svc.update_task(session, task_id, user_id=user.id, **kwargs)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return TaskOut.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await svc.delete_task(session, task_id, user_id=user.id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
