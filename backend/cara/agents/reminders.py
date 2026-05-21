"""Reminders (Memorial) Celery agent.

Two scheduled tasks running on the `learn` worker:

  * `scan_due` — every minute. Picks pending `reminder_notifications`
    whose `scheduled_at <= now()` and fan-outs each via `enqueue_for_backend`
    so the backend lifespan consumer ships push + Telegram + WS-TTS.
  * `materialize_recurrences` — every night at 03:30. Sweeps active
    reminders and re-checks that future notification rows exist.
    Idempotent. Safety net for any drift after a deploy / DB restore.

Why a separate queue from the existing ones: reminders.scan_due runs
at 1-min cadence — the tightest cadence in the system. Putting it
behind the same worker as Gmail polling (15 min) or habit detection
(nightly) would let a slow ingestion task delay a "you have a visit
in 2 hours" notification. The `learn` queue handles 30s watchdog ticks
already so it's the right home.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select

from cara.agents._base import _get_sessionmaker, cara_task
from cara.models.reminder import Reminder
from cara.services import reminders as svc
from cara.services.notify import (
    Notification,
    TelegramAction,
    enqueue_for_backend,
)


log = structlog.get_logger(__name__)


_PRE_LABEL = {
    60: "fra 1 ora",
    120: "fra 2 ore",
    180: "fra 3 ore",
    720: "fra 12 ore",
    1440: "domani",
    10080: "fra 7 giorni",
    20160: "fra 14 giorni",
    43200: "fra 30 giorni",
    86400: "fra 60 giorni",
    129600: "fra 90 giorni",
}


def _humanise_minutes(m: int) -> str:
    if m in _PRE_LABEL:
        return _PRE_LABEL[m]
    if m >= 1440 and m % 1440 == 0:
        return f"fra {m // 1440} giorni"
    if m >= 60 and m % 60 == 0:
        return f"fra {m // 60} ore"
    return f"fra {m} min"


def _format_local(dt: datetime) -> str:
    """Format `dt` for human consumption — Europe/Rome."""
    # Best-effort: zoneinfo isn't always present on alpine. Fall back
    # to a +02:00 offset which is correct for most of the year in IT.
    try:
        from zoneinfo import ZoneInfo
        local = dt.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:  # noqa: BLE001
        local = dt
    return local.strftime("%d/%m/%Y alle %H:%M")


def _category_emoji(category: str) -> str:
    return {
        "family": "👨‍👩‍👧",
        "health": "🩺",
        "documents": "📄",
        "events": "🎉",
    }.get(category, "📌")


def _build_notification(reminder: Reminder, kind: str) -> Notification:
    """Map a reminder + notification kind ('due' / 'pre_<min>') to a
    Notification ready for fan-out."""
    when = _format_local(reminder.due_at)
    emoji = _category_emoji(reminder.category)

    if kind == "due":
        title = f"{emoji} {reminder.title}"
        body = f"È il momento. {when}."
    else:
        # kind = "pre_<minutes>"
        try:
            mins = int(kind.split("_", 1)[1])
        except (IndexError, ValueError):
            mins = 0
        when_phrase = _humanise_minutes(mins) if mins else "presto"
        title = f"{emoji} Promemoria · {reminder.title}"
        body = f"{when_phrase.capitalize()} ({when})."

    if reminder.notes:
        body = f"{body}\n{reminder.notes}"

    rid = str(reminder.id)
    return Notification(
        kind=f"reminder.{kind}",
        title=title,
        body=body,
        tag=f"reminder:{rid}:{kind}",
        deep_link=f"/reminders/{rid}",
        severity="info",
        target_user_ids=[reminder.user_id] + (
            [reminder.family_id] if reminder.family_id else []
        ),
        telegram_actions=[[
            TelegramAction(label="✅ Fatto", callback_data=f"reminder:done:{rid}"),
            TelegramAction(label="⏰ +1h",   callback_data=f"reminder:snz:{rid}:60"),
            TelegramAction(label="⏰ Domani", callback_data=f"reminder:snz:{rid}:1440"),
        ]],
    )


@cara_task(agent="learn", name="cara.agents.reminders.scan_due")
async def scan_due(idempotency_key: str | None = None) -> dict[str, Any]:
    """One tick: deliver every overdue notification, mark as sent."""
    sm = _get_sessionmaker()
    sent = 0
    failed = 0
    now = datetime.now(UTC)

    async with sm() as session:
        rows = await svc.due_notifications(session, until=now)
        if not rows:
            return {"sent": 0, "failed": 0, "checked": 0}

        for notif_row in rows:
            # Load the parent reminder. We deliberately fetch fresh so
            # any concurrent status change (done / archived) is seen.
            reminder = (await session.execute(
                select(Reminder).where(Reminder.id == notif_row.reminder_id)
            )).scalar_one_or_none()
            if reminder is None or reminder.status in ("done", "archived"):
                # Reminder gone or terminal — flag the row as sent so we
                # don't keep retrying.
                await svc.mark_notification_sent(
                    session, notif_row.id, delivery={"skipped": "reminder_terminal"},
                )
                continue

            try:
                notif = _build_notification(reminder, notif_row.kind)
                await enqueue_for_backend(notif)
                await svc.mark_notification_sent(
                    session, notif_row.id, delivery={"enqueued": True},
                )
                sent += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.warning(
                    "reminders.scan_due.dispatch_failed",
                    reminder_id=str(reminder.id),
                    error=str(exc)[:200],
                )
                # Leave sent_at NULL so the next tick retries.

        await session.commit()

    return {"sent": sent, "failed": failed, "checked": len(rows)}


@cara_task(agent="learn", name="cara.agents.reminders.materialize_recurrences")
async def materialize_recurrences(
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Nightly sweep — backfill any missing future notifications.

    Safety net: if a deploy bug, DB restore, or manual edit ever
    leaves an active reminder without its pre-notice rows, the next
    midnight pass fixes it.
    """
    sm = _get_sessionmaker()
    async with sm() as session:
        n = await svc.refresh_active_notifications(session)
        await session.commit()
    return {"refreshed": n}


__all__ = ["scan_due", "materialize_recurrences"]
