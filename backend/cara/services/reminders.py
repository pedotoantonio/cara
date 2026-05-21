"""Reminders (Memorial) service layer.

Pure async persistence + scheduling logic for guided "human" reminders.
Three responsibilities:

  1. **CRUD** on `reminders` rows, scoped by `user_id` (the *creator*;
     the optional `family_id` is the subject the reminder is about).
  2. **Notification materialisation**: for each active reminder we
     pre-compute the rows in `reminder_notifications` that the
     Celery scanner will eventually fire. Doing this synchronously at
     write-time keeps the scanner trivial — just look for `sent_at IS
     NULL AND scheduled_at <= now() + grace`.
  3. **Recurrence**: when a reminder is marked `done`, if it carries
     a `recurrence` we advance `due_at` to the next occurrence and
     re-materialise notifications. Yearly = +1 year, monthly = +1
     calendar month, weekly = +7 days.

The service NEVER imports from the API layer; the router orchestrates.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.reminder import (
    CATEGORIES,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_DONE,
    STATUS_SNOOZED,
    Reminder,
    ReminderNotification,
    ReminderTemplate,
)

log = structlog.get_logger(__name__)


# ─── Templates ─────────────────────────────────────────────────────


async def list_templates(
    session: AsyncSession, *, category: str | None = None
) -> list[ReminderTemplate]:
    stmt = select(ReminderTemplate)
    if category:
        stmt = stmt.where(ReminderTemplate.category == category)
    stmt = stmt.order_by(
        ReminderTemplate.category.asc(),
        ReminderTemplate.order_in_category.asc(),
        ReminderTemplate.title_it.asc(),
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_template_by_slug(
    session: AsyncSession, slug: str
) -> ReminderTemplate | None:
    stmt = select(ReminderTemplate).where(ReminderTemplate.slug == slug)
    return (await session.execute(stmt)).scalar_one_or_none()


# ─── Reminders ─────────────────────────────────────────────────────


async def list_reminders(
    session: AsyncSession,
    *,
    user_id: int,
    upcoming_days: int | None = None,
    category: str | None = None,
    include_done: bool = False,
) -> list[Reminder]:
    """List the reminders for which `user_id` is creator OR subject.

    Filtering rules:
      * `upcoming_days` → due within +N days from now (still includes
        overdue active items so users see ⚠️ "in ritardo").
      * `category` → match exactly.
      * `include_done` → include status=done/archived; default off.
    """
    now = datetime.now(UTC)
    stmt = select(Reminder).where(
        or_(Reminder.user_id == user_id, Reminder.family_id == user_id)
    )
    if not include_done:
        stmt = stmt.where(
            Reminder.status.in_([STATUS_ACTIVE, STATUS_SNOOZED])
        )
    if category:
        stmt = stmt.where(Reminder.category == category)
    if upcoming_days is not None:
        end = now + timedelta(days=upcoming_days)
        # Overdue ALWAYS visible: due_at <= end and (active or not yet done).
        stmt = stmt.where(Reminder.due_at <= end)
    stmt = stmt.order_by(Reminder.due_at.asc())
    return list((await session.execute(stmt)).scalars().all())


async def get_reminder(
    session: AsyncSession, reminder_id: uuid.UUID, *, user_id: int
) -> Reminder | None:
    stmt = select(Reminder).where(
        Reminder.id == reminder_id,
        or_(Reminder.user_id == user_id, Reminder.family_id == user_id),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_reminder(
    session: AsyncSession,
    *,
    user_id: int,
    title: str,
    category: str,
    due_at: datetime,
    template_slug: str | None = None,
    family_id: int | None = None,
    notes: str | None = None,
    recurrence: str | None = None,
    recurrence_until: date | None = None,
    lead_times: list[int] | None = None,
    channels: dict[str, Any] | None = None,
) -> Reminder:
    if category not in CATEGORIES:
        raise ValueError(f"unknown category: {category}")
    reminder = Reminder(
        user_id=user_id,
        family_id=family_id,
        template_slug=template_slug,
        category=category,
        title=title,
        notes=notes,
        due_at=_ensure_aware(due_at),
        recurrence=recurrence,
        recurrence_until=recurrence_until,
        lead_times=list(lead_times or []),
        channels=channels or {"push": True, "telegram": True},
        status=STATUS_ACTIVE,
    )
    session.add(reminder)
    await session.flush()
    await _materialise_notifications(session, reminder)
    return reminder


async def create_from_template(
    session: AsyncSession,
    *,
    user_id: int,
    template_slug: str,
    due_at: datetime,
    family_id: int | None = None,
    extras: dict[str, Any] | None = None,
    title_override: str | None = None,
    notes: str | None = None,
    lead_times: list[int] | None = None,
    recurrence: str | None = None,
) -> Reminder:
    """Resolve the template, derive title + defaults, persist."""
    tmpl = await get_template_by_slug(session, template_slug)
    if tmpl is None:
        raise ValueError(f"unknown template: {template_slug}")

    title = title_override or _compose_title(tmpl, extras or {})

    return await create_reminder(
        session,
        user_id=user_id,
        title=title,
        category=tmpl.category,
        due_at=due_at,
        template_slug=tmpl.slug,
        family_id=family_id,
        notes=notes,
        recurrence=recurrence if recurrence is not None else tmpl.default_recurrence,
        lead_times=lead_times if lead_times is not None else list(tmpl.default_lead_times),
    )


def _compose_title(tmpl: ReminderTemplate, extras: dict[str, Any]) -> str:
    """Build a human title from template + extras.

    Heuristics, in order:
      1. If `extras` has a `subject_label` or `who_label` (human-friendly
         name of the family member), append it: "Visita medica · Tony".
      2. Else fall back to the template title.
    """
    base = tmpl.title_it
    label = extras.get("subject_label") or extras.get("who_label")
    if isinstance(label, str) and label.strip():
        return f"{base} · {label.strip()}"[:300]
    return base[:300]


async def update_reminder(
    session: AsyncSession,
    reminder_id: uuid.UUID,
    *,
    user_id: int,
    title: str | None = None,
    notes: str | None | object = ...,
    due_at: datetime | None = None,
    family_id: int | None | object = ...,
    recurrence: str | None | object = ...,
    recurrence_until: date | None | object = ...,
    lead_times: list[int] | None = None,
    channels: dict[str, Any] | None = None,
    status: str | None = None,
) -> Reminder | None:
    reminder = await get_reminder(session, reminder_id, user_id=user_id)
    if reminder is None:
        return None

    rescheduled = False
    if title is not None:
        reminder.title = title[:300]
    if notes is not ...:
        reminder.notes = notes  # type: ignore[assignment]
    if due_at is not None:
        reminder.due_at = _ensure_aware(due_at)
        rescheduled = True
    if family_id is not ...:
        reminder.family_id = family_id  # type: ignore[assignment]
    if recurrence is not ...:
        reminder.recurrence = recurrence  # type: ignore[assignment]
    if recurrence_until is not ...:
        reminder.recurrence_until = recurrence_until  # type: ignore[assignment]
    if lead_times is not None:
        reminder.lead_times = list(lead_times)
        rescheduled = True
    if channels is not None:
        reminder.channels = channels
    if status is not None:
        reminder.status = status
        if status == STATUS_DONE and reminder.completed_at is None:
            reminder.completed_at = datetime.now(UTC)
        if status == STATUS_ACTIVE:
            reminder.completed_at = None
            reminder.snooze_until = None

    reminder.updated_at = datetime.now(UTC)
    if rescheduled:
        await _materialise_notifications(session, reminder, replace=True)

    await session.flush()
    return reminder


async def delete_reminder(
    session: AsyncSession, reminder_id: uuid.UUID, *, user_id: int
) -> bool:
    reminder = await get_reminder(session, reminder_id, user_id=user_id)
    if reminder is None:
        return False
    await session.delete(reminder)  # CASCADE removes notifications
    await session.flush()
    return True


async def mark_done(
    session: AsyncSession, reminder_id: uuid.UUID, *, user_id: int
) -> Reminder | None:
    """Mark done. If recurring, advance to next occurrence and stay active."""
    reminder = await get_reminder(session, reminder_id, user_id=user_id)
    if reminder is None:
        return None

    if reminder.recurrence:
        next_due = _next_occurrence(reminder.due_at, reminder.recurrence)
        if next_due and (
            reminder.recurrence_until is None
            or next_due.date() <= reminder.recurrence_until
        ):
            # Roll forward in place — keep the same reminder row so the
            # user's history stays clean (one row per "thing", not one
            # row per occurrence).
            reminder.due_at = next_due
            reminder.completed_at = None
            reminder.status = STATUS_ACTIVE
            reminder.snooze_until = None
            reminder.updated_at = datetime.now(UTC)
            await _materialise_notifications(session, reminder, replace=True)
            await session.flush()
            return reminder

    # Terminal: one-shot or end-of-series.
    reminder.status = STATUS_DONE
    reminder.completed_at = datetime.now(UTC)
    reminder.updated_at = datetime.now(UTC)
    # Cancel still-pending notifications so the user doesn't get a
    # ghost push after marking done.
    await session.execute(
        delete(ReminderNotification).where(
            ReminderNotification.reminder_id == reminder.id,
            ReminderNotification.sent_at.is_(None),
        )
    )
    await session.flush()
    return reminder


async def snooze(
    session: AsyncSession,
    reminder_id: uuid.UUID,
    *,
    user_id: int,
    duration_minutes: int | None = None,
    until: datetime | None = None,
) -> Reminder | None:
    reminder = await get_reminder(session, reminder_id, user_id=user_id)
    if reminder is None:
        return None
    if until is None and duration_minutes is None:
        duration_minutes = 60
    target = _ensure_aware(until) if until else datetime.now(UTC) + timedelta(
        minutes=int(duration_minutes or 60)
    )
    reminder.snooze_until = target
    reminder.status = STATUS_SNOOZED
    reminder.updated_at = datetime.now(UTC)
    # Don't touch due_at — when the snooze window expires the scanner
    # re-evaluates against `due_at` plus the lead-time grid.
    await session.flush()
    return reminder


# ─── Notification materialisation ──────────────────────────────────


async def _materialise_notifications(
    session: AsyncSession, reminder: Reminder, *, replace: bool = False
) -> None:
    """(Re-)compute pre + due notification rows for a reminder.

    `lead_times` is a list of minutes-before-due. For each, we insert
    one row at `due_at - lead`. We also always insert one `due` row
    at `due_at` itself, unless lead_times explicitly contains 0.

    Idempotent via the unique constraint on (reminder_id, kind,
    scheduled_at). With `replace=True` we first DELETE all unsent
    rows for the reminder, then re-insert.
    """
    if replace:
        await session.execute(
            delete(ReminderNotification).where(
                ReminderNotification.reminder_id == reminder.id,
                ReminderNotification.sent_at.is_(None),
            )
        )

    now = datetime.now(UTC)
    rows: list[ReminderNotification] = []

    pre_minutes = sorted({int(m) for m in (reminder.lead_times or []) if int(m) > 0})
    for m in pre_minutes:
        sched = reminder.due_at - timedelta(minutes=m)
        if sched <= now:
            # Don't materialise pre-notices that are already in the past;
            # they'd just fire immediately on next scan.
            continue
        rows.append(ReminderNotification(
            reminder_id=reminder.id,
            scheduled_at=sched,
            kind=f"pre_{m}",
        ))

    # The "due" notification — always (it's the main one).
    if reminder.due_at > now:
        rows.append(ReminderNotification(
            reminder_id=reminder.id,
            scheduled_at=reminder.due_at,
            kind="due",
        ))

    for r in rows:
        # ON CONFLICT DO NOTHING via try/except per-row is simpler than
        # a multi-VALUES upsert here (we always have ≤ 4 rows).
        session.add(r)
        try:
            await session.flush()
        except Exception:  # noqa: BLE001
            await session.rollback()
            # Per-row failure is fine — the constraint already saved us
            # from a duplicate. Reload the reminder to keep the session
            # consistent.
            await session.refresh(reminder)


# ─── Recurrence helpers ────────────────────────────────────────────


def _next_occurrence(current: datetime, recurrence: str) -> datetime | None:
    """Advance `current` by one step of `recurrence`. Returns None for
    unknown patterns."""
    if recurrence == "yearly":
        try:
            return current.replace(year=current.year + 1)
        except ValueError:
            # 29 Feb → 28 Feb on a non-leap year.
            return current.replace(month=2, day=28, year=current.year + 1)
    if recurrence == "monthly":
        m = current.month + 1
        y = current.year
        if m > 12:
            m = 1
            y += 1
        # Clamp day to last day of the next month.
        try:
            return current.replace(year=y, month=m)
        except ValueError:
            # Day overflow — back off to 28 (safe for every month).
            return current.replace(year=y, month=m, day=28)
    if recurrence == "weekly":
        return current + timedelta(days=7)
    return None


def _ensure_aware(dt: datetime) -> datetime:
    """Force tz-aware (UTC default) so DB comparisons don't blow up."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# ─── Scanner queries (used by the Celery task) ─────────────────────


async def due_notifications(
    session: AsyncSession, *, until: datetime
) -> list[ReminderNotification]:
    """Return notifications that should fire NOW (sent_at NULL,
    scheduled_at <= until) for non-archived non-done reminders that
    are not currently snoozed past `scheduled_at`."""
    stmt = (
        select(ReminderNotification)
        .join(Reminder, Reminder.id == ReminderNotification.reminder_id)
        .where(
            ReminderNotification.sent_at.is_(None),
            ReminderNotification.scheduled_at <= until,
            Reminder.status.in_([STATUS_ACTIVE, STATUS_SNOOZED]),
            or_(
                Reminder.snooze_until.is_(None),
                Reminder.snooze_until <= ReminderNotification.scheduled_at,
            ),
        )
        .order_by(ReminderNotification.scheduled_at.asc())
        .limit(200)
    )
    return list((await session.execute(stmt)).scalars().all())


async def mark_notification_sent(
    session: AsyncSession,
    notif_id: uuid.UUID,
    *,
    delivery: dict[str, Any] | None = None,
) -> None:
    stmt = select(ReminderNotification).where(ReminderNotification.id == notif_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return
    row.sent_at = datetime.now(UTC)
    if delivery:
        row.delivery = delivery
    await session.flush()


# ─── Recurrence batch (nightly beat) ───────────────────────────────


async def refresh_active_notifications(session: AsyncSession) -> int:
    """Sweep all active reminders, ensure their future notifications
    are materialised. Idempotent — useful as a safety net after
    schema migrations or a Redis flush."""
    stmt = select(Reminder).where(Reminder.status == STATUS_ACTIVE)
    count = 0
    for reminder in (await session.execute(stmt)).scalars():
        await _materialise_notifications(session, reminder, replace=False)
        count += 1
    return count


__all__ = [
    "create_from_template",
    "create_reminder",
    "delete_reminder",
    "due_notifications",
    "get_reminder",
    "get_template_by_slug",
    "list_reminders",
    "list_templates",
    "mark_done",
    "mark_notification_sent",
    "refresh_active_notifications",
    "snooze",
    "update_reminder",
]
