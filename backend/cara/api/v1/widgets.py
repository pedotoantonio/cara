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
        # Wires to a per-user location once /me/preferences ships;
        # for now the widget falls back to "available: false".
        return None

    async def presence() -> list[PresenceBrief]:
        # Wires to frigate-faces when its API is bridged into CARA.
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


def _register_for_request(session: AsyncSession):
    """Re-register the catalog with request-scoped fetchers and return
    the registry. Cheap: just rebuilds 7 in-memory closures."""
    fetchers = _make_fetchers(session)
    reg = get_default_registry()
    register_all(fetchers, registry=reg)
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
