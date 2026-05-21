"""Reminders (Memorial) — guided human reminders.

NOT a task manager. The UX flow is: pick a category (4 fixed), pick
a "situation" template (e.g. "Hai una visita prenotata?"), fill 2-3
fields, save. Everything else (lead-times, recurrence) is derived
from the template defaults.

Auth: every endpoint requires a logged-in user. A reminder is visible
to its creator (`user_id`) AND to the subject (`family_id`) when set.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.reminder import CATEGORIES
from cara.models.user import User
from cara.schemas.reminder import (
    ReminderCreate,
    ReminderOut,
    ReminderTemplateOut,
    ReminderUpdate,
    SnoozeIn,
)
from cara.services import reminders as svc
from cara.services.family_bus import publish as fb_publish
from cara.store import get_session

router = APIRouter(prefix="/reminders", tags=["reminders"])


# ─── Templates ─────────────────────────────────────────────────────


@router.get("/templates", response_model=list[ReminderTemplateOut])
async def list_templates(
    category: str | None = Query(default=None),
    _user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ReminderTemplateOut]:
    if category is not None and category not in CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown category")
    rows = await svc.list_templates(session, category=category)
    return [ReminderTemplateOut.model_validate(r) for r in rows]


# ─── Reminders ─────────────────────────────────────────────────────


@router.get("", response_model=list[ReminderOut])
async def list_my_reminders(
    upcoming_days: int | None = Query(default=None, ge=0, le=365),
    category: str | None = Query(default=None),
    include_done: bool = Query(default=False),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ReminderOut]:
    if category is not None and category not in CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown category")
    rows = await svc.list_reminders(
        session,
        user_id=user.id,
        upcoming_days=upcoming_days,
        category=category,
        include_done=include_done,
    )
    return [ReminderOut.model_validate(r) for r in rows]


@router.get("/upcoming", response_model=list[ReminderOut])
async def upcoming(
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ReminderOut]:
    rows = await svc.list_reminders(
        session, user_id=user.id, upcoming_days=days, include_done=False
    )
    return [ReminderOut.model_validate(r) for r in rows[:limit]]


@router.post("", response_model=ReminderOut, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    body: ReminderCreate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ReminderOut:
    if body.template_slug:
        try:
            reminder = await svc.create_from_template(
                session,
                user_id=user.id,
                template_slug=body.template_slug,
                due_at=body.due_at,
                family_id=body.family_id,
                extras=body.extras,
                title_override=body.title,
                notes=body.notes,
                lead_times=body.lead_times,
                recurrence=body.recurrence,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    else:
        if not body.title or not body.category:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "title + category richiesti (oppure usa template_slug)",
            )
        try:
            reminder = await svc.create_reminder(
                session,
                user_id=user.id,
                title=body.title,
                category=body.category,
                due_at=body.due_at,
                family_id=body.family_id,
                notes=body.notes,
                recurrence=body.recurrence,
                recurrence_until=body.recurrence_until,
                lead_times=body.lead_times,
                channels=body.channels,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    out = ReminderOut.model_validate(reminder)
    await fb_publish(
        "reminder.created", user_id=user.id, payload=out.model_dump(mode="json")
    )
    return out


@router.patch("/{reminder_id}", response_model=ReminderOut)
async def update_reminder(
    reminder_id: uuid.UUID,
    body: ReminderUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ReminderOut:
    # PATCH semantics: pass only fields actually set in the body.
    kwargs: dict[str, Any] = {}
    fields = body.model_fields_set
    if "title" in fields:
        kwargs["title"] = body.title
    if "notes" in fields:
        kwargs["notes"] = body.notes
    if "due_at" in fields:
        kwargs["due_at"] = body.due_at
    if "family_id" in fields:
        kwargs["family_id"] = body.family_id
    if "recurrence" in fields:
        kwargs["recurrence"] = body.recurrence
    if "recurrence_until" in fields:
        kwargs["recurrence_until"] = body.recurrence_until
    if "lead_times" in fields:
        kwargs["lead_times"] = body.lead_times
    if "channels" in fields:
        kwargs["channels"] = body.channels
    if "status" in fields:
        kwargs["status"] = body.status

    reminder = await svc.update_reminder(
        session, reminder_id, user_id=user.id, **kwargs
    )
    if reminder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    out = ReminderOut.model_validate(reminder)
    await fb_publish(
        "reminder.updated", user_id=user.id, payload=out.model_dump(mode="json")
    )
    return out


@router.post("/{reminder_id}/done", response_model=ReminderOut)
async def mark_done(
    reminder_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ReminderOut:
    reminder = await svc.mark_done(session, reminder_id, user_id=user.id)
    if reminder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    out = ReminderOut.model_validate(reminder)
    await fb_publish(
        "reminder.done", user_id=user.id, payload=out.model_dump(mode="json")
    )
    return out


@router.post("/{reminder_id}/snooze", response_model=ReminderOut)
async def snooze(
    reminder_id: uuid.UUID,
    body: SnoozeIn,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ReminderOut:
    reminder = await svc.snooze(
        session,
        reminder_id,
        user_id=user.id,
        duration_minutes=body.duration_minutes,
        until=body.until,
    )
    if reminder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    out = ReminderOut.model_validate(reminder)
    await fb_publish(
        "reminder.snoozed", user_id=user.id, payload=out.model_dump(mode="json")
    )
    return out


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(
    reminder_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await svc.delete_reminder(session, reminder_id, user_id=user.id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    await fb_publish(
        "reminder.deleted", user_id=user.id, payload={"id": str(reminder_id)}
    )
