"""Reminder scheduler — scans tasks with upcoming `due_date` and pushes.

Run as an asyncio background task from FastAPI's lifespan. Every
`push_scheduler_interval_seconds` (default 60s) we:

  1. Find tasks where:
       - done = false
       - due_date IS NOT NULL
       - reminded_at IS NULL
       - due_date <= NOW + lead_minutes
  2. For each, fan-out a Push to every active subscription of that user.
  3. Mark `reminded_at = now` so the next tick doesn't re-push.

Conservative: a task whose due_date passes WITHOUT being reminded (e.g.
the scheduler was down) will still trigger on the next run, because the
window is `due_date <= now + lead`. We don't suppress past-due ones — a
late "ricorda di andare al dentista alle 9" is more useful than no
notification at all.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from cara.config import settings
from cara.models.task import Task
from cara.services.push import PushPayload, is_configured, send_to_user


log = structlog.get_logger(__name__)


def _format_when(due: datetime) -> str:
    """Italian "alle HH:MM" / "domani alle HH:MM" / etc."""
    now = datetime.now(timezone.utc)
    diff = (due - now).total_seconds()
    if abs(diff) < 60:
        return "ora"
    if diff < 0 and abs(diff) < 60 * 60:
        return f"{int(abs(diff) // 60)} min fa"
    if diff < 0:
        return "in ritardo"
    if diff < 60 * 90:
        return f"tra {int(diff // 60)} min"
    # Local time for display.
    try:
        from zoneinfo import ZoneInfo

        local = due.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:  # noqa: BLE001
        local = due
    today = datetime.now(local.tzinfo or timezone.utc).date()
    target = local.date()
    hhmm = local.strftime("%H:%M")
    if target == today:
        return f"oggi alle {hhmm}"
    if (target - today).days == 1:
        return f"domani alle {hhmm}"
    return local.strftime("%d/%m alle %H:%M")


async def _scan_once(sessionmaker: async_sessionmaker) -> int:
    """One sweep — return number of reminders pushed."""
    if not is_configured():
        return 0

    lead = timedelta(minutes=settings.push_reminder_lead_minutes)
    now = datetime.now(timezone.utc)
    cutoff = now + lead

    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(Task)
                .where(Task.done.is_(False))
                .where(Task.due_date.is_not(None))
                .where(Task.reminded_at.is_(None))
                .where(Task.due_date <= cutoff)
                .order_by(Task.due_date)
                .limit(50)
            )
        ).scalars().all()

        if not rows:
            return 0

        log.info("push_scheduler.due_tasks_found", count=len(rows))
        sent = 0
        for t in rows:
            assert t.due_date is not None  # noqa: S101 — narrowed above
            payload = PushPayload(
                title="Promemoria",
                body=f"{t.title} — {_format_when(t.due_date)}",
                tag=f"task-{t.id}",
                url="/tasks",
            )
            try:
                delivered = await send_to_user(session, user_id=t.user_id, payload=payload)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "push_scheduler.send_failed", task_id=str(t.id), error=str(exc),
                )
                continue
            # Mark reminded_at even if no devices were subscribed — the
            # user might subscribe later, and we don't want a queued
            # backlog firing on the first device that ever subscribes.
            await session.execute(
                update(Task).where(Task.id == t.id).values(reminded_at=now)
            )
            sent += delivered
        await session.commit()
        return sent


async def run_loop(sessionmaker: async_sessionmaker) -> None:
    """Long-running scheduler — call once from app lifespan."""
    interval = max(15, settings.push_scheduler_interval_seconds)
    log.info("push_scheduler.start", interval_seconds=interval)
    try:
        while True:
            try:
                pushed = await _scan_once(sessionmaker)
                if pushed:
                    log.info("push_scheduler.tick_done", pushed=pushed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                # Never let a bad row crash the whole loop.
                log.warning("push_scheduler.tick_error", error=str(exc))
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("push_scheduler.stop")
        raise
