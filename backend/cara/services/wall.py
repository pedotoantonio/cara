"""Wall surface data assembly.

`/api/v1/wall/*` is a public read-only API: any caller on the LAN gets
the family agenda (today, calendar, week) without authentication. The
filters here decide WHAT can be exposed:

  - users: `wall_visible=True` only (guests opt-out by default)
  - tasks: `wall_visible=True` (per-record toggle)
  - calendar_events: `wall_visible=True` (per-record toggle)

Output shapes are intentionally compact — we don't ship descriptions /
locations / chat history. The Wall MUST be safe to read from across the
room.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.calendar_event import CalendarEvent
from cara.models.task import Task
from cara.models.user import User
from cara.services import admin_settings as admin_svc
from cara.services import family as family_svc

log = structlog.get_logger(__name__)


# ─── Roster ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class WallUser:
    id: int
    display_name: str
    role: str
    color: str
    emoji: str
    wall_visible: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "role": self.role,
            "color": self.color,
            "emoji": self.emoji,
            "wall_visible": self.wall_visible,
        }


_PALETTE_FALLBACK = (
    "#f59e0b", "#10b981", "#3b82f6", "#ef4444",
    "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
)
_ROLE_EMOJI_FALLBACK = {
    "parent": "👤", "teen": "🎒", "child": "🧸",
    "elder": "👴", "guest": "👋",
}


def _user_to_wall(u: User, idx: int) -> WallUser:
    """Resolve display fields with sensible fallbacks if the migration
    didn't backfill yet (e.g. user created mid-flight)."""
    name = (u.full_name or u.email.split("@")[0] or "?").strip()
    color = u.wall_color or _PALETTE_FALLBACK[idx % len(_PALETTE_FALLBACK)]
    emoji = u.wall_emoji or _ROLE_EMOJI_FALLBACK.get(u.role, "👤")
    return WallUser(
        id=u.id,
        display_name=name,
        role=u.role,
        color=color,
        emoji=emoji,
        wall_visible=bool(u.wall_visible),
    )


async def list_family(session: AsyncSession) -> list[WallUser]:
    """All active family members in stable id-order. Includes everyone
    so the admin UI can flip wall_visible — the wall data filters them
    later."""
    rows = (
        await session.execute(
            select(User)
            .where(User.is_active.is_(True))
            .order_by(User.id.asc())
        )
    ).scalars().all()
    return [_user_to_wall(u, i) for i, u in enumerate(rows)]


async def visible_owner_index(session: AsyncSession) -> dict[int, WallUser]:
    """Map user_id → WallUser for all users with wall_visible=True."""
    everyone = await list_family(session)
    return {u.id: u for u in everyone if u.wall_visible}


# ─── Tasks ───────────────────────────────────────────────────────────


def _task_to_dict(task: Task, owner: WallUser | None) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "title": (task.title or "").strip()[:120],
        "due_date": task.due_date.astimezone(UTC).isoformat() if task.due_date else None,
        "done": bool(task.done),
        "owner_id": task.user_id,
        "owner": owner.to_dict() if owner else None,
        "kind": "task",
    }


async def tasks_in_range(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    owner_index: dict[int, WallUser],
) -> list[dict[str, Any]]:
    """Tasks whose due_date falls in [start, end). Tasks without
    due_date are NOT included here (they go in the "no date" bucket)."""
    rows = (
        await session.execute(
            select(Task)
            .where(
                Task.wall_visible.is_(True),
                Task.user_id.in_(owner_index.keys()),
                Task.due_date.is_not(None),
                Task.due_date >= start,
                Task.due_date < end,
            )
            .order_by(Task.due_date.asc())
        )
    ).scalars().all()
    return [_task_to_dict(t, owner_index.get(t.user_id)) for t in rows]


async def open_tasks_no_date(
    session: AsyncSession,
    *,
    owner_index: dict[int, WallUser],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Open (not done) tasks without a due_date — shown in the 'oggi'
    section after the timed entries."""
    rows = (
        await session.execute(
            select(Task)
            .where(
                Task.wall_visible.is_(True),
                Task.done.is_(False),
                Task.user_id.in_(owner_index.keys()),
                Task.due_date.is_(None),
            )
            .order_by(Task.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_task_to_dict(t, owner_index.get(t.user_id)) for t in rows]


async def pending_tasks_by_owner(
    session: AsyncSession,
    *,
    owner_index: dict[int, WallUser],
    horizon_days: int = 14,
) -> dict[str, Any]:
    """Counts of open tasks per owner for the next horizon_days, used
    to render the 'X ha 3 task aperti' chip on Today."""
    cutoff = datetime.now(UTC) + timedelta(days=horizon_days)
    rows = (
        await session.execute(
            select(Task)
            .where(
                Task.wall_visible.is_(True),
                Task.done.is_(False),
                Task.user_id.in_(owner_index.keys()),
                or_(Task.due_date.is_(None), Task.due_date <= cutoff),
            )
        )
    ).scalars().all()

    by_owner: dict[int, int] = {}
    overdue: dict[int, int] = {}
    now = datetime.now(UTC)
    for t in rows:
        by_owner[t.user_id] = by_owner.get(t.user_id, 0) + 1
        if t.due_date and t.due_date < now:
            overdue[t.user_id] = overdue.get(t.user_id, 0) + 1
    return {
        "by_owner": [
            {
                "owner": owner_index[uid].to_dict(),
                "count": cnt,
                "overdue": overdue.get(uid, 0),
            }
            for uid, cnt in sorted(
                by_owner.items(), key=lambda kv: kv[1], reverse=True
            )
        ],
    }


# ─── Calendar events ─────────────────────────────────────────────────


def _event_to_dict(ev: CalendarEvent, owner: WallUser | None) -> dict[str, Any]:
    return {
        "id": ev.id,
        "title": (ev.title or "").strip()[:120] or "(senza titolo)",
        "start": ev.start_at.astimezone(UTC).isoformat() if ev.start_at else None,
        "end": ev.end_at.astimezone(UTC).isoformat() if ev.end_at else None,
        "all_day": bool(ev.all_day),
        "owner_id": ev.user_id,
        "owner": owner.to_dict() if owner else None,
        "kind": "event",
    }


async def events_in_range(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    owner_index: dict[int, WallUser],
) -> list[dict[str, Any]]:
    """Calendar events overlapping [start, end)."""
    rows = (
        await session.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.wall_visible.is_(True),
                CalendarEvent.user_id.in_(owner_index.keys()),
                CalendarEvent.start_at.is_not(None),
                # Overlap test: event.end >= range.start AND event.start < range.end
                or_(
                    CalendarEvent.end_at.is_(None),
                    CalendarEvent.end_at >= start,
                ),
                CalendarEvent.start_at < end,
            )
            .order_by(CalendarEvent.start_at.asc())
        )
    ).scalars().all()
    return [_event_to_dict(e, owner_index.get(e.user_id)) for e in rows]


# ─── Today summary ───────────────────────────────────────────────────


def _local_day_bounds(now_utc: datetime, day_offset: int = 0) -> tuple[datetime, datetime]:
    """Return UTC bounds of the local calendar day (Europe/Rome) at
    `now + day_offset days`. We treat the date as Europe/Rome to match
    what the user sees on a wall clock; the boundaries we send to SQL
    are UTC because that's what the columns store."""
    # Cheap approach: drop tz and compute on naive local. UTC offset
    # for Europe/Rome is +1 winter / +2 summer. We use the actual
    # localised value via astimezone if zoneinfo is available.
    try:
        from zoneinfo import ZoneInfo
        local_now = now_utc.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:  # noqa: BLE001
        local_now = now_utc
    target_date = local_now.date() + timedelta(days=day_offset)
    start_local = datetime.combine(target_date, time.min).replace(
        tzinfo=local_now.tzinfo
    )
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


async def build_today_summary(
    session: AsyncSession,
) -> dict[str, Any]:
    """Bundle for the Wall Today view:
        - today: ordered list of events+tasks for today
        - upcoming: brief view of next 3 days (counts + top 3 each)
        - family: roster (who's visible on Wall)
        - presence: who's currently in the house (fallback empty)
        - pending_by_owner: counts of open tasks per family member
    """
    now = datetime.now(UTC)
    owners = await visible_owner_index(session)
    everyone = await list_family(session)

    # Today
    t_start, t_end = _local_day_bounds(now, 0)
    today_tasks = await tasks_in_range(
        session, start=t_start, end=t_end, owner_index=owners
    )
    today_events = await events_in_range(
        session, start=t_start, end=t_end, owner_index=owners
    )
    no_date_open = await open_tasks_no_date(session, owner_index=owners, limit=15)

    today_items = sorted(
        today_tasks + today_events,
        key=lambda x: x.get("start") or x.get("due_date") or "9999",
    )

    # Upcoming (next 3 days)
    upcoming = []
    for offset in range(1, 4):
        s, e = _local_day_bounds(now, offset)
        day_t = await tasks_in_range(session, start=s, end=e, owner_index=owners)
        day_e = await events_in_range(session, start=s, end=e, owner_index=owners)
        merged = sorted(
            day_t + day_e,
            key=lambda x: x.get("start") or x.get("due_date") or "9999",
        )
        upcoming.append({
            "date": s.astimezone(_get_zone()).date().isoformat(),
            "count": len(merged),
            "preview": merged[:3],
        })

    pending = await pending_tasks_by_owner(session, owner_index=owners)

    # Presence — best effort, never block the bundle on a frigate-faces
    # outage.
    presence: dict[str, Any] = {"available": False, "people": []}
    try:
        rows = await family_svc.people_present(window_minutes=15)
        presence = {
            "available": True,
            "people": [
                {
                    "name": p.name,
                    "minutes_ago": p.minutes_ago,
                }
                for p in rows
            ],
        }
    except family_svc.FamilyPresenceUnavailable:
        pass

    weather_block = await _build_weather_block(session)

    return {
        "now": now.isoformat(),
        "today": {
            "items": today_items,
            "open_no_date": no_date_open,
        },
        "upcoming": upcoming,
        "family": [u.to_dict() for u in everyone],
        "pending_by_owner": pending["by_owner"],
        "presence": presence,
        "weather": weather_block,
    }


def _get_zone():  # noqa: ANN202
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:  # noqa: BLE001
        return UTC


# ─── Weather (best-effort) ───────────────────────────────────────────


async def _build_weather_block(session: AsyncSession) -> dict[str, Any]:
    lat = await admin_svc.get(session, "family_lat")
    lon = await admin_svc.get(session, "family_lon")
    city = await admin_svc.get(session, "family_city")
    if lat is None or lon is None:
        return {"available": False, "city": city}
    try:
        from cara.services.weather import WeatherService  # noqa: PLC0415
        svc = WeatherService()
        try:
            current = await svc.current(float(lat), float(lon))
        finally:
            await svc.aclose()
    except Exception as exc:  # noqa: BLE001
        log.warning("wall.weather.failed", error=str(exc))
        return {"available": False, "city": city}
    if current is None:
        return {"available": False, "city": city}
    return {
        "available": True,
        "city": city,
        "label": current.label,
        "icon_slug": current.icon_slug,
        "temperature_c": round(current.temperature_c, 1),
        "apparent_c": (
            round(current.apparent_temperature_c, 1)
            if current.apparent_temperature_c is not None else None
        ),
        "is_day": bool(current.is_day),
    }


# ─── Calendar grid (month) ───────────────────────────────────────────


async def build_calendar_grid(
    session: AsyncSession,
    *,
    year: int,
    month: int,
) -> dict[str, Any]:
    """Build a month-view grid (6 weeks × 7 days, Lun-Dom) covering the
    requested month; includes leading/trailing days so the grid is
    rectangular. Each day carries up to 60 chars of items."""
    if not (1 <= month <= 12):
        raise ValueError(f"invalid month {month}")
    if not (1900 <= year <= 2100):
        raise ValueError(f"invalid year {year}")

    zone = _get_zone()
    first_day = date(year, month, 1)
    # Monday=0 … Sunday=6. We start the grid on the Monday of the week
    # containing the 1st.
    weekday = first_day.weekday()
    grid_start = first_day - timedelta(days=weekday)
    grid_days = 42  # 6 weeks
    grid_end = grid_start + timedelta(days=grid_days)

    start_dt = datetime.combine(grid_start, time.min, tzinfo=zone).astimezone(UTC)
    end_dt = datetime.combine(grid_end, time.min, tzinfo=zone).astimezone(UTC)

    owners = await visible_owner_index(session)

    tasks = await tasks_in_range(
        session, start=start_dt, end=end_dt, owner_index=owners
    )
    events = await events_in_range(
        session, start=start_dt, end=end_dt, owner_index=owners
    )
    bdays = await birthday_index(session)

    # Bucket by local date
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in tasks + events:
        iso = item.get("start") or item.get("due_date")
        if not iso:
            continue
        try:
            ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        local_day = ts.astimezone(zone).date().isoformat()
        buckets.setdefault(local_day, []).append(item)

    # Sort each bucket by time
    for k in buckets:
        buckets[k].sort(
            key=lambda x: x.get("start") or x.get("due_date") or "9999"
        )

    # Build day cells
    from cara.services.saints import saint_for  # noqa: PLC0415
    days = []
    for i in range(grid_days):
        d = grid_start + timedelta(days=i)
        iso = d.isoformat()
        days.append({
            "date": iso,
            "in_month": d.month == month,
            "is_today": d == datetime.now(zone).date(),
            "is_weekend": d.weekday() >= 5,
            "is_holiday": _is_italian_holiday(d),
            "is_pre_holiday": _is_pre_holiday(d),
            "saint": saint_for(d),
            "birthdays": bdays.get((d.month, d.day), []),
            "items": buckets.get(iso, []),
        })

    return {
        "year": year,
        "month": month,
        "grid_start": grid_start.isoformat(),
        "grid_end": (grid_end - timedelta(days=1)).isoformat(),
        "days": days,
        "family": [u.to_dict() for u in (await list_family(session))],
    }


# ─── Italian fixed-date holidays ─────────────────────────────────────
# Easter / Pasquetta are date-dependent; we compute via a simple
# Anonymous Gregorian algorithm.

def _easter_sunday(y: int) -> date:
    a = y % 19
    b = y // 100
    c = y % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


_FIXED_HOLIDAYS: set[tuple[int, int]] = {
    (1, 1),    # Capodanno
    (1, 6),    # Epifania
    (4, 25),   # Festa della Liberazione
    (5, 1),    # Festa del lavoro
    (6, 2),    # Festa della Repubblica
    (8, 15),   # Ferragosto
    (11, 1),   # Tutti i santi
    (12, 8),   # Immacolata
    (12, 25),  # Natale
    (12, 26),  # Santo Stefano
}


def _is_italian_holiday(d: date) -> bool:
    """Italian "festivo": Sundays, fixed national holidays, and Easter
    Sunday + Pasquetta. Used by the wall to paint the day red."""
    if d.weekday() == 6:  # Sunday
        return True
    if (d.month, d.day) in _FIXED_HOLIDAYS:
        return True
    easter = _easter_sunday(d.year)
    return d == easter or d == (easter + timedelta(days=1))


def _is_pre_holiday(d: date) -> bool:
    """Italian "prefestivo": the day BEFORE a holiday, provided the day
    itself isn't already a holiday. Saturdays therefore qualify (next
    day is Sunday). The wall paints the day-number orange."""
    if _is_italian_holiday(d):
        return False
    return _is_italian_holiday(d + timedelta(days=1))


# ─── Birthdays ───────────────────────────────────────────────────────


async def birthday_index(
    session: AsyncSession,
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """(month, day) → list of birthday entries `{user_id, name, color,
    emoji, born_year}`. Only users with `wall_visible=True` and a
    `birth_date` set are included."""
    rows = (
        await session.execute(
            select(User)
            .where(
                User.is_active.is_(True),
                User.wall_visible.is_(True),
                User.birth_date.is_not(None),
            )
            .order_by(User.id.asc())
        )
    ).scalars().all()

    out: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for idx, u in enumerate(rows):
        if u.birth_date is None:
            continue
        wu = _user_to_wall(u, idx)
        key = (u.birth_date.month, u.birth_date.day)
        out.setdefault(key, []).append({
            "user_id": u.id,
            "name": wu.display_name,
            "color": wu.color,
            "emoji": wu.emoji,
            "born_year": u.birth_date.year,
        })
    return out


# ─── Week view ───────────────────────────────────────────────────────


async def build_week(
    session: AsyncSession,
    *,
    start: date,
) -> dict[str, Any]:
    """7 days starting at `start` (assumed Monday). Returns the same
    day-bucket shape as the month grid, plus the same family roster."""
    zone = _get_zone()
    days_count = 7
    grid_end = start + timedelta(days=days_count)
    start_dt = datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC)
    end_dt = datetime.combine(grid_end, time.min, tzinfo=zone).astimezone(UTC)
    owners = await visible_owner_index(session)
    tasks = await tasks_in_range(
        session, start=start_dt, end=end_dt, owner_index=owners
    )
    events = await events_in_range(
        session, start=start_dt, end=end_dt, owner_index=owners
    )
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in tasks + events:
        iso = item.get("start") or item.get("due_date")
        if not iso:
            continue
        try:
            ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        local_day = ts.astimezone(zone).date().isoformat()
        buckets.setdefault(local_day, []).append(item)
    for k in buckets:
        buckets[k].sort(
            key=lambda x: x.get("start") or x.get("due_date") or "9999"
        )
    from cara.services.saints import saint_for  # noqa: PLC0415
    bdays = await birthday_index(session)
    days = []
    today = datetime.now(zone).date()
    for i in range(days_count):
        d = start + timedelta(days=i)
        iso = d.isoformat()
        days.append({
            "date": iso,
            "is_today": d == today,
            "is_weekend": d.weekday() >= 5,
            "is_holiday": _is_italian_holiday(d),
            "is_pre_holiday": _is_pre_holiday(d),
            "saint": saint_for(d),
            "birthdays": bdays.get((d.month, d.day), []),
            "items": buckets.get(iso, []),
        })
    return {
        "start": start.isoformat(),
        "end": (grid_end - timedelta(days=1)).isoformat(),
        "days": days,
        "family": [u.to_dict() for u in (await list_family(session))],
    }
