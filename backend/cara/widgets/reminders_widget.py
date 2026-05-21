"""Reminders widget — "I prossimi 3 ricordi" per Wallet e Wall.

Cheap: una sola query con LIMIT 3, indicizzata su (user_id, due_at).
Cache-friendly: il refresh interval è 5 minuti — i reminder cambiano
raramente, la lista ai limiti del giorno (oggi/domani) cambia naturalmente
all'arrivo della scadenza che il backend gestisce comunque via push.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.reminder import (
    STATUS_ACTIVE,
    STATUS_SNOOZED,
    Reminder,
)
from cara.widgets.base import Widget, WidgetContext, WidgetData, WidgetSize


_CATEGORY_EMOJI = {
    "family": "👨‍👩‍👧",
    "health": "🩺",
    "documents": "📄",
    "events": "🎉",
}


class RemindersUpcomingWidget(Widget):
    """Show up to 3 next reminders (active OR snoozed past their window)."""

    id = "reminders_upcoming"
    title_default = "Prossimi ricordi"
    refresh_interval_s = 300                  # 5 min
    available_for_roles: tuple[str, ...] = () # tutti

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def render(
        self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM,
    ) -> WidgetData:
        if ctx.user_id is None:
            return WidgetData(
                widget_id=self.id, title=self.title_default, kind="list",
                body={"items": [], "empty_label": "Accedi per vedere i ricordi"},
                deep_link="/reminders",
            )

        now = datetime.now(UTC)
        # 30-day forward window — far enough to surface document
        # expirations, short enough that the strip never goes stale.
        until = now + timedelta(days=30)

        stmt = (
            select(Reminder)
            .where(
                or_(Reminder.user_id == ctx.user_id,
                    Reminder.family_id == ctx.user_id),
                Reminder.status.in_([STATUS_ACTIVE, STATUS_SNOOZED]),
                Reminder.due_at <= until,
            )
            .order_by(Reminder.due_at.asc())
            .limit(3)
        )

        cap = 3 if ctx.surface_class != "wall" else 4
        rows = list((await self._session.execute(stmt)).scalars().all())[:cap]

        items = [
            {
                "id": str(r.id),
                "title": r.title,
                "category": r.category,
                "emoji": _CATEGORY_EMOJI.get(r.category, "📌"),
                "due_at": r.due_at.isoformat(),
                "overdue": r.due_at < now,
            }
            for r in rows
        ]

        return WidgetData(
            widget_id=self.id,
            title=self.title_default,
            kind="reminders_list",
            body={
                "items": items,
                "empty_label": "Niente nei prossimi 30 giorni 🌿",
            },
            deep_link="/reminders",
            last_updated_unix=time.time(),
        )


def register(session: AsyncSession, registry) -> None:  # type: ignore[no-untyped-def]
    """Register the reminders widget with the provided registry."""
    registry.register(RemindersUpcomingWidget(session))
