"""Catalog of built-in widgets.

Each widget is a small class that pulls one piece of family state and
returns a `WidgetData` payload the frontend renders. They never raise
on fail — they fall back to a sensible empty state. They never make
expensive calls — anything that would hit the LLM, OCR, or do heavy
DB work is wrapped behind a service boundary the widget calls cheaply.

Shipped widgets (Step 7.2):
  - `today_summary`         tasks today + presence + weather one-liner
  - `tasks_mine`            top-3 user tasks by due date
  - `shopping_quick`        unchecked shopping list (capped 6 items)
  - `notes_recent`          last 3 notes
  - `weather_now`           current temp + WMO icon for the user's city
  - `presence`              who is currently in the house
  - `quick_actions`         configurable shortcut grid

A registry helper at the bottom batch-registers them with the default
WidgetRegistry — useful for tests or for the eventual `main.py` wiring.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from cara.widgets.base import (
    Widget,
    WidgetContext,
    WidgetData,
    WidgetRegistry,
    WidgetSize,
    get_default_registry,
)


# ---------------------------------------------------------------------------
# Data fetchers — Protocols so widgets can be tested without a real DB
# ---------------------------------------------------------------------------


@dataclass
class TaskBrief:
    id: str
    title: str
    done: bool
    due_unix: float | None


@dataclass
class ShoppingBrief:
    id: int
    title: str
    qty: str | None
    bought: bool


@dataclass
class NoteBrief:
    id: int
    title: str
    body_preview: str
    updated_unix: float


@dataclass
class WeatherBrief:
    temperature_c: float
    label: str
    icon_slug: str
    is_day: bool
    location: str = ""               # "Ferrara" — shown in the widget header
    apparent_temperature_c: float | None = None


@dataclass
class PresenceBrief:
    name: str
    last_seen_unix: float


# Each fetcher is the *signature* — concrete implementations are wired
# from cara.services.* once chat.py is split. Widgets accept fetchers
# in their constructor so unit tests pass canned data and don't need a
# DB / Redis.

class _Fetchers:
    """Container for the (testable) fetcher callables a widget needs."""

    def __init__(
        self,
        *,
        tasks_for: Any | None = None,         # async (user_id) -> list[TaskBrief]
        shopping_for: Any | None = None,      # async (user_id) -> list[ShoppingBrief]
        notes_for: Any | None = None,         # async (user_id) -> list[NoteBrief]
        weather_for: Any | None = None,       # async (user_id) -> WeatherBrief | None
        presence: Any | None = None,          # async () -> list[PresenceBrief]
    ) -> None:
        self.tasks_for = tasks_for
        self.shopping_for = shopping_for
        self.notes_for = notes_for
        self.weather_for = weather_for
        self.presence = presence


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class TodaySummaryWidget:
    id = "today_summary"
    title_default = "Oggi"
    refresh_interval_s = 300
    available_for_roles: tuple[str, ...] = ()

    def __init__(self, fetchers: _Fetchers) -> None:
        self._f = fetchers

    async def render(self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM) -> WidgetData:
        tasks_today = 0
        weather_summary = None
        present_count = 0
        if self._f.tasks_for is not None and ctx.user_id is not None:
            tasks = await self._f.tasks_for(ctx.user_id)
            now = time.time()
            tasks_today = sum(
                1 for t in tasks if not t.done and t.due_unix and t.due_unix <= now + 86400
            )
        if self._f.weather_for is not None and ctx.user_id is not None:
            w = await self._f.weather_for(ctx.user_id)
            if w is not None:
                weather_summary = {
                    "temperature_c": round(w.temperature_c, 1),
                    "label": w.label,
                    "icon_slug": w.icon_slug,
                }
        if self._f.presence is not None:
            present_count = len(await self._f.presence())
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="summary",
            body={
                "tasks_today": tasks_today,
                "weather": weather_summary,
                "present_count": present_count,
            },
            deep_link=None,
            last_updated_unix=time.time(),
        )


class TasksMineWidget:
    id = "tasks_mine"
    title_default = "I miei task"
    refresh_interval_s = 60
    available_for_roles: tuple[str, ...] = ()

    def __init__(self, fetchers: _Fetchers) -> None:
        self._f = fetchers

    async def render(self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM) -> WidgetData:
        tasks: list[TaskBrief] = []
        if self._f.tasks_for is not None and ctx.user_id is not None:
            all_tasks = await self._f.tasks_for(ctx.user_id)
            # Open tasks first; then by earliest due date; then by title.
            open_tasks = [t for t in all_tasks if not t.done]
            open_tasks.sort(key=lambda t: (
                t.due_unix if t.due_unix is not None else float("inf"),
                t.title.lower(),
            ))
            limit = 3 if size == WidgetSize.SMALL else 5
            tasks = open_tasks[:limit]
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="list",
            body={
                "items": [
                    {
                        "id": t.id, "title": t.title,
                        "due_unix": t.due_unix, "done": t.done,
                    }
                    for t in tasks
                ],
                "total_open": len(tasks),
            },
            deep_link="/tasks",
            last_updated_unix=time.time(),
        )


class ShoppingQuickWidget:
    id = "shopping_quick"
    title_default = "Lista spesa"
    refresh_interval_s = 30
    available_for_roles: tuple[str, ...] = ()

    def __init__(self, fetchers: _Fetchers) -> None:
        self._f = fetchers

    async def render(self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM) -> WidgetData:
        items: list[ShoppingBrief] = []
        if self._f.shopping_for is not None and ctx.user_id is not None:
            all_items = await self._f.shopping_for(ctx.user_id)
            unchecked = [i for i in all_items if not i.bought]
            items = unchecked[:6]
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="checklist",
            body={
                "items": [{"id": i.id, "title": i.title, "qty": i.qty} for i in items],
                "total_unchecked": len(items),
            },
            deep_link="/shopping",
            last_updated_unix=time.time(),
        )


class NotesRecentWidget:
    id = "notes_recent"
    title_default = "Note recenti"
    refresh_interval_s = 120
    available_for_roles: tuple[str, ...] = ()

    def __init__(self, fetchers: _Fetchers) -> None:
        self._f = fetchers

    async def render(self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM) -> WidgetData:
        notes: list[NoteBrief] = []
        if self._f.notes_for is not None and ctx.user_id is not None:
            all_notes = await self._f.notes_for(ctx.user_id)
            notes = sorted(all_notes, key=lambda n: n.updated_unix, reverse=True)[:3]
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="list",
            body={
                "items": [
                    {
                        "id": n.id, "title": n.title, "preview": n.body_preview,
                        "updated_unix": n.updated_unix,
                    }
                    for n in notes
                ],
            },
            deep_link="/notes",
            last_updated_unix=time.time(),
        )


class WeatherNowWidget:
    id = "weather_now"
    title_default = "Meteo"
    refresh_interval_s = 900
    available_for_roles: tuple[str, ...] = ()

    def __init__(self, fetchers: _Fetchers) -> None:
        self._f = fetchers

    async def render(self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM) -> WidgetData:
        body: dict[str, Any] = {"available": False}
        if self._f.weather_for is not None and ctx.user_id is not None:
            w = await self._f.weather_for(ctx.user_id)
            if w is not None:
                body = {
                    "available": True,
                    "temperature_c": round(w.temperature_c, 1),
                    "apparent_temperature_c": (
                        round(w.apparent_temperature_c, 1)
                        if w.apparent_temperature_c is not None
                        else None
                    ),
                    "label": w.label,
                    "icon_slug": w.icon_slug,
                    "is_day": w.is_day,
                    "location": w.location,
                }
        title = (
            f"Meteo · {body['location']}"
            if body.get("location")
            else self.title_default
        )
        # `kind="weather"` routes the body through the dedicated
        # WeatherView in the frontend (icon + temp + apparent + label).
        return WidgetData(
            widget_id=self.id, title=title, kind="weather",
            body=body, deep_link="/weather", last_updated_unix=time.time(),
        )


class PresenceWidget:
    id = "presence"
    title_default = "Chi è in casa"
    refresh_interval_s = 60
    available_for_roles: tuple[str, ...] = ()

    def __init__(self, fetchers: _Fetchers) -> None:
        self._f = fetchers

    async def render(self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM) -> WidgetData:
        people: list[PresenceBrief] = []
        if self._f.presence is not None:
            people = await self._f.presence()
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="presence",
            body={
                "people": [
                    {"name": p.name, "last_seen_unix": p.last_seen_unix}
                    for p in people
                ],
                "count": len(people),
            },
            deep_link="/family",
            last_updated_unix=time.time(),
        )


class QuickActionsWidget:
    """Dashboard shortcut grid. Actions are configured per-user (Step 7.3)."""

    id = "quick_actions"
    title_default = "Azioni rapide"
    refresh_interval_s = 0  # static — no refresh
    available_for_roles: tuple[str, ...] = ()

    DEFAULT_ACTIONS: tuple[dict[str, str], ...] = (
        {"id": "add_task", "label": "Nuovo task", "icon": "plus", "deep_link": "/tasks/new"},
        {"id": "add_shopping", "label": "Aggiungi spesa", "icon": "shopping", "deep_link": "/shopping/new"},
        {"id": "add_note", "label": "Nota rapida", "icon": "note", "deep_link": "/notes/new"},
        {"id": "voice", "label": "Parla a CARA", "icon": "mic", "deep_link": "/chat?voice=1"},
    )

    async def render(self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM) -> WidgetData:
        # User config wins; default fallback otherwise.
        configured = ctx.config.get("actions") if ctx.config else None
        actions = list(configured) if configured else list(self.DEFAULT_ACTIONS)
        # Cap by surface — small surfaces get fewer.
        cap = {"watch": 2, "mobile": 4, "wall": 4, "desktop": 6, "tv": 6}.get(
            ctx.surface_class, 4
        )
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="action_grid",
            body={"actions": actions[:cap]},
            last_updated_unix=time.time(),
        )


# ---------------------------------------------------------------------------
# Batch registration helper
# ---------------------------------------------------------------------------


def register_all(
    fetchers: _Fetchers,
    *,
    registry: WidgetRegistry | None = None,
) -> WidgetRegistry:
    """Register every catalog widget on `registry` (default: process-wide)."""
    reg = registry or get_default_registry()
    for cls in (
        TodaySummaryWidget,
        TasksMineWidget,
        ShoppingQuickWidget,
        NotesRecentWidget,
        WeatherNowWidget,
        PresenceWidget,
    ):
        reg.register(cls(fetchers))
    reg.register(QuickActionsWidget())
    return reg
