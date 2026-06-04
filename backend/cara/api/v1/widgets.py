"""Wallet endpoints — list available widgets + render N at once.

The frontend asks for a comma-separated list of widget ids to render
in the order the user wants them. The backend renders each (catching
per-widget exceptions as inline error payloads) and returns the array.

  GET /api/v1/widgets                        → catalog (id, title, refresh)
  GET /api/v1/widgets/render?ids=a,b,c       → rendered payloads in order
  GET /api/v1/widgets/{widget_id}            → render a single widget

A registered fetcher set lives at module level. Real fetchers wire into
`cara.services.tasks`, `cara.services.shopping`, etc. — for now we
ship sensible default fetchers that read user state.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.services import notes as notes_svc
from cara.services import shopping as shopping_svc
from cara.services import tasks as tasks_svc
from cara.store import get_session
from cara.widgets import (
    WidgetContext,
    WidgetData,
    WidgetSize,
    get_default_registry,
)
from cara.widgets.catalog import (
    NoteBrief,
    PresenceBrief,
    ShoppingBrief,
    TaskBrief,
    WeatherBrief,
    _Fetchers,
    register_all,
)
from cara.widgets.catalog_extra import (
    _ExtraFetchers,
    register_extras,
)


router = APIRouter(prefix="/widgets", tags=["widgets"])


# ---------------------------------------------------------------------------
# Fetchers — wired to existing services
# ---------------------------------------------------------------------------


_REGISTRY_INITIALISED = False


def _make_fetchers(session: AsyncSession) -> _Fetchers:
    """Bind the catalog widgets to a request-scoped session."""

    async def tasks_for(user_id: int) -> list[TaskBrief]:
        rows = await tasks_svc.list_tasks(session, user_id=user_id, include_done=False)
        out: list[TaskBrief] = []
        for r in rows:
            due_unix = r.due_date.timestamp() if r.due_date else None
            out.append(TaskBrief(
                id=str(r.id), title=r.title, done=r.done, due_unix=due_unix,
            ))
        return out

    async def shopping_for(user_id: int) -> list[ShoppingBrief]:
        rows = await shopping_svc.list_items(session, user_id=user_id)
        return [
            ShoppingBrief(id=r.id, title=r.title, qty=r.qty, bought=r.bought)
            for r in rows
        ]

    async def notes_for(user_id: int) -> list[NoteBrief]:
        rows = await notes_svc.list_notes(session, user_id=user_id)
        out: list[NoteBrief] = []
        for r in rows:
            preview = (r.body or "").strip().split("\n", 1)[0][:120]
            updated = (r.updated_at or r.created_at).timestamp()
            out.append(NoteBrief(id=r.id, title=r.title or "(senza titolo)",
                                 body_preview=preview, updated_unix=updated))
        return out

    async def weather_for(user_id: int) -> WeatherBrief | None:
        # Reads family residence from admin_settings (set via the
        # /admin/settings → "family_lat/family_lon/family_city") and
        # asks Open-Meteo for the current observation. Cached at the
        # WeatherService layer (15 min Redis TTL) so this fetcher is
        # cheap to call on every wallet render.
        from cara.services import admin_settings as _admin  # noqa: PLC0415
        from cara.services.weather import WeatherService  # noqa: PLC0415

        try:
            lat = await _admin.get(session, "family_lat")
            lon = await _admin.get(session, "family_lon")
            city = await _admin.get(session, "family_city")
        except Exception:  # noqa: BLE001
            return None
        if lat is None or lon is None:
            return None
        try:
            ws = WeatherService()
            cur = await ws.current(float(lat), float(lon))
        except Exception:  # noqa: BLE001
            return None
        if cur is None:
            return None
        return WeatherBrief(
            temperature_c=cur.temperature_c,
            apparent_temperature_c=cur.apparent_temperature_c,
            label=cur.label,
            icon_slug=cur.icon_slug,
            is_day=cur.is_day,
            location=str(city or ""),
        )

    async def presence() -> list[PresenceBrief]:
        # Presence is now driven by the in-browser face recognition stack
        # (src/features/face) — server-side widgets don't know who is in
        # front of which device, so the Wall presence widget stays empty.
        return []

    return _Fetchers(
        tasks_for=tasks_for,
        shopping_for=shopping_for,
        notes_for=notes_for,
        weather_for=weather_for,
        presence=presence,
    )


def _ensure_registry() -> None:
    """Register the catalog widgets exactly once per process."""
    global _REGISTRY_INITIALISED
    if _REGISTRY_INITIALISED:
        return
    # Catalog widgets close over the fetchers passed at register-time —
    # but our fetchers are session-scoped. Solution: register the catalog
    # with a placeholder set, then the request handlers swap in a fresh
    # per-request _Fetchers instance through a sub-class with no state.
    # Simpler approach for now: register once with PLACEHOLDER fetchers
    # and re-register on every render with the request-scoped ones.
    # That's what `_register_for_request` below does.
    _REGISTRY_INITIALISED = True


def _make_extras(session: AsyncSession) -> _ExtraFetchers:
    """Bind the 6 extra widgets (Step 7.6) to a request-scoped session."""

    async def budget_rollup(year: int, month: int) -> dict[str, Any]:
        from cara.services import budgets as budget_svc
        rollup = await budget_svc.month_rollup(session, year=year, month=month)
        return rollup.to_dict()

    async def kids_homework(user_id: int) -> list[dict[str, Any]]:
        # Heuristic: tasks whose title mentions a school keyword. Once
        # the data model adds a `category` column we'll filter on that
        # instead. Conservative — we don't want to surface a private
        # task as "homework" because the title says "scuola".
        rows = await tasks_svc.list_tasks(
            session, user_id=user_id, include_done=False,
        )
        keywords = ("compit", "scuola", "lezion", "verifica", "interrog", "studi")
        out: list[dict[str, Any]] = []
        for t in rows:
            title_lower = (t.title or "").lower()
            if not any(k in title_lower for k in keywords):
                continue
            out.append({
                "id": str(t.id),
                "title": t.title,
                "done": bool(t.done),
                "due_unix": t.due_date.timestamp() if t.due_date else None,
            })
        return out

    async def habit_next(user_id: int) -> list[dict[str, Any]]:
        # Walks accepted habit candidates for `user_id`. Sorted: active
        # weekday matches first, then by hour bucket.
        from datetime import datetime
        from sqlalchemy import select
        from cara.models.habit import HABIT_STATUS_ACCEPTED, HabitCandidate

        rows = list((await session.execute(
            select(HabitCandidate)
            .where(HabitCandidate.user_id == user_id)
            .where(HabitCandidate.status == HABIT_STATUS_ACCEPTED)
            .order_by(HabitCandidate.confidence.desc())
            .limit(20)
        )).scalars().all())
        if not rows:
            return []
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Europe/Rome"))
        except Exception:
            now = datetime.now()
        cur_wd = now.weekday()
        cur_hb = now.hour // 3
        # Distance metric: same weekday=0; +7 for next-week wrap.
        # Inside the day, |hour_bucket - now_bucket| breaks the tie.
        def _distance(c: HabitCandidate) -> tuple[int, int]:
            wd_delta = (c.weekday - cur_wd) % 7
            hb_delta = abs(c.hour_bucket - cur_hb)
            return (wd_delta, hb_delta)
        rows.sort(key=_distance)
        return [
            {
                "kind": c.kind,
                "weekday": c.weekday,
                "hour_bucket": c.hour_bucket,
                "pattern": c.pattern,
                "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            }
            for c in rows[:5]
        ]

    async def news_brief(category: str, limit: int) -> list[dict[str, Any]]:
        # Lazy-import: cara.services.news pulls feedparser which is a
        # heavy dependency we don't want at module import time.
        try:
            from cara.services import news as news_svc
        except ImportError:
            return []
        try:
            items = await news_svc.fetch_category(category, limit=limit)
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for it in items:
            out.append({
                "title": getattr(it, "title", "") or it.get("title", ""),
                "summary": (
                    getattr(it, "summary", None) or it.get("summary", "")
                )[:200] if isinstance(it, dict) or hasattr(it, "summary") else "",
                "source": getattr(it, "source", None) or it.get("source", ""),
                "link": getattr(it, "link", None) or it.get("link", ""),
            })
        return out

    async def now_playing() -> dict[str, Any] | None:
        # Frontend audio playback owns this state. The backend keeps it
        # in admin_settings under "radio_now_playing" — when nothing's
        # active, the value is empty/None.
        from cara.services import admin_settings as setting_svc
        info = await setting_svc.get(session, "radio_now_playing")
        if not info or not isinstance(info, dict):
            return None
        return info

    async def diet_summary(user_id: int) -> dict[str, Any] | None:
        """Professional nutrition report: today's energy balance +
        this week's adherence per protein category + macros + water."""
        from cara.services import diet as diet_svc
        from cara.services import diet_energy

        today = diet_svc.rome_today()
        energy = await diet_energy.energy_stats(
            session, user_id=user_id, period="day", anchor=today
        )

        # Weekly adherence per protein category vs the active plan.
        plan = await diet_svc.get_active_plan(session, user_id)
        rules = await diet_svc.get_rules(session, plan.id) if plan else {}
        rollup = await diet_svc.week_rollup(session, user_id, today)
        adherence = diet_svc.adherence_score(rollup.consumed, rules)
        categories = []
        for cat in ("legumi", "pesce", "carne", "uova", "formaggio"):
            rule = rules.get(cat)
            consumed = rollup.consumed.get(cat, 0)
            categories.append({
                "category": cat,
                "color": diet_svc.color_for(cat),
                "consumed": consumed,
                "target_min": rule.target_min if rule else None,
                "target_max": rule.target_max if rule else None,
                "state": diet_svc.category_state(consumed, rule),
            })

        # Today's macros from logged meals (sum over parsed items via CREA
        # is not stored per-macro; we surface kcal + water + adherence,
        # which is what the plan actually tracks).
        intake = await diet_svc.get_intake(session, user_id, today)

        return {
            "available": True,
            "profile_complete": energy.profile_complete,
            # Energy balance (today)
            "bmr": energy.bmr,
            "tdee": energy.tdee,
            "daily_target": energy.daily_target,
            "consumed": energy.consumed,
            "burned": energy.burned,
            "remaining": energy.remaining,
            # Weekly adherence
            "adherence_score": adherence,
            "avg_kcal_per_day": rollup.avg_kcal_per_day,
            "categories": categories,
            "days_logged": rollup.days_logged,
            # Hydration today
            "water_ml": intake.water_ml,
            "coffee_count": intake.coffee_count,
        }

    return _ExtraFetchers(
        budget_rollup=budget_rollup,
        kids_homework=kids_homework,
        habit_next=habit_next,
        news_brief=news_brief,
        now_playing=now_playing,
        diet_summary=diet_summary,
    )


def _register_for_request(session: AsyncSession):
    """Re-register the catalog with request-scoped fetchers and return
    the registry. Cheap: rebuilds 7 + 6 in-memory closures."""
    fetchers = _make_fetchers(session)
    reg = get_default_registry()
    register_all(fetchers, registry=reg)
    register_extras(_make_extras(session), registry=reg)
    # Reminders (Memorial) — pulls reminders directly via session.
    from cara.widgets import reminders_widget as _rem  # noqa: PLC0415
    _rem.register(session, reg)
    return reg


# ---------------------------------------------------------------------------
# Catalog endpoint
# ---------------------------------------------------------------------------


@router.get("")
async def list_widgets(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """List the widgets visible to this user (filtered by role)."""
    reg = _register_for_request(session)
    visible = reg.available_for(user.role)
    return {
        "widgets": [
            {
                "id": w.id,
                "title": getattr(w, "title_default", w.id),
                "refresh_interval_s": getattr(w, "refresh_interval_s", 60),
            }
            for w in visible
        ],
    }


# ---------------------------------------------------------------------------
# Render endpoints
# ---------------------------------------------------------------------------


def _ctx_from(user: User, surface_class: str = "mobile") -> WidgetContext:
    return WidgetContext(
        user_id=user.id,
        user_role=user.role or "guest",
        surface_class=surface_class,
        locale="it-IT",
        timezone="Europe/Rome",
    )


def _payloads_to_dict(payloads: list[WidgetData]) -> list[dict[str, Any]]:
    return [p.to_dict() for p in payloads]


@router.get("/render")
async def render_widgets(
    ids: str = Query(..., description="Comma-separated widget ids in render order"),
    surface: str = Query(default="mobile", pattern="^(wall|mobile|desktop|watch|tv)$"),
    size: str = Query(default="medium", pattern="^(small|medium|large)$"),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Render the requested widgets in order."""
    requested = [s.strip() for s in ids.split(",") if s.strip()]
    if not requested:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no widget ids provided")
    if len(requested) > 32:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "too many widgets requested (max 32)"
        )

    reg = _register_for_request(session)
    ctx = _ctx_from(user, surface_class=surface)
    payloads = await reg.render_many(requested, ctx, size=WidgetSize(size))
    return {
        "rendered_at_unix": time.time(),
        "items": _payloads_to_dict(payloads),
    }


@router.get("/{widget_id}")
async def render_one(
    widget_id: str,
    surface: str = Query(default="mobile", pattern="^(wall|mobile|desktop|watch|tv)$"),
    size: str = Query(default="medium", pattern="^(small|medium|large)$"),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Convenience: render a single widget by id."""
    reg = _register_for_request(session)
    if reg.get(widget_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown widget: {widget_id}")
    ctx = _ctx_from(user, surface_class=surface)
    [payload] = await reg.render_many([widget_id], ctx, size=WidgetSize(size))
    return payload.to_dict()
