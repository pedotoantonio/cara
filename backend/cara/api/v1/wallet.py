"""Wallet layout REST API (Step 7.4 + 7.5).

  GET    /api/v1/wallet/layout?surface=mobile     current layout
  PUT    /api/v1/wallet/layout?surface=mobile     replace layout
  DELETE /api/v1/wallet/layout?surface=mobile     reset to default
  GET    /api/v1/wallet/presets                   list 4 preset profiles
  POST   /api/v1/wallet/preset/{slug}?surface=    apply preset

The actual widget rendering still goes through `/api/v1/widgets/render`.
This module only manages the order + size + per-widget config.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.services import wallet_layouts as svc
from cara.store import get_session


router = APIRouter(prefix="/wallet", tags=["wallet"])


# ---------------------------------------------------------------- schemas


class WidgetEntry(BaseModel):
    widget_id: str = Field(min_length=1, max_length=80)
    size: str = Field(default="medium", pattern="^(small|medium|large)$")
    config: dict[str, Any] = Field(default_factory=dict)


class LayoutOut(BaseModel):
    surface_class: str
    items: list[WidgetEntry]
    preset: str | None
    is_default: bool


class LayoutPut(BaseModel):
    items: list[WidgetEntry] = Field(default_factory=list, max_length=32)


class PresetOut(BaseModel):
    slug: str
    label: str
    description: str
    items: list[WidgetEntry]


# ---------------------------------------------------------------- helpers


_SURFACE_REGEX = "^(wall|mobile|desktop|watch|tv)$"


def _surface_param(surface: str = Query(..., pattern=_SURFACE_REGEX)) -> str:
    return surface


# ---------------------------------------------------------------- endpoints


@router.get("/layout", response_model=LayoutOut)
async def get_my_layout(
    surface: str = Depends(_surface_param),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> LayoutOut:
    """Returns the user's saved layout, or the project default if no
    row exists yet (with `is_default=True` so the UI can prompt
    "Vuoi iniziare con un preset?")."""
    items, preset = await svc.get_or_default(
        session, user_id=user.id, surface_class=surface,
    )
    has_row = preset is not None  # default returns preset=None
    return LayoutOut(
        surface_class=surface,
        items=[WidgetEntry(**i) for i in items],
        preset=preset,
        is_default=not has_row,
    )


@router.put("/layout", response_model=LayoutOut)
async def replace_my_layout(
    body: LayoutPut,
    surface: str = Depends(_surface_param),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> LayoutOut:
    """Replace the user's layout for `surface_class`. Marks `preset="custom"`
    because explicit edits detach from any preset."""
    row = await svc.upsert_layout(
        session,
        user_id=user.id, surface_class=surface,
        items=[i.model_dump() for i in body.items],
        preset="custom",
        commit=True,
    )
    return LayoutOut(
        surface_class=row.surface_class,
        items=[WidgetEntry(**i) for i in row.items],
        preset=row.preset,
        is_default=False,
    )


@router.delete("/layout", status_code=status.HTTP_204_NO_CONTENT)
async def reset_my_layout(
    surface: str = Depends(_surface_param),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Reset to default for the given surface. The default is the
    canonical fallback shipped in `wallet_layouts.py`."""
    await svc.reset_layout(
        session, user_id=user.id, surface_class=surface, commit=True,
    )


@router.get("/presets", response_model=list[PresetOut])
async def list_presets(
    user: User = Depends(get_current_user),  # noqa: B008
) -> list[PresetOut]:
    return [
        PresetOut(
            slug=p.slug,
            label=p.label,
            description=p.description,
            items=[WidgetEntry(**dict(i)) for i in p.items],
        )
        for p in svc.PRESETS
    ]


@router.post("/preset/{preset_slug}", response_model=LayoutOut)
async def apply_preset_to_my_layout(
    preset_slug: str,
    surface: str = Depends(_surface_param),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> LayoutOut:
    """One-click apply a preset to the user's layout for `surface_class`."""
    try:
        row = await svc.apply_preset(
            session,
            user_id=user.id, surface_class=surface,
            preset_slug=preset_slug, commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return LayoutOut(
        surface_class=row.surface_class,
        items=[WidgetEntry(**i) for i in row.items],
        preset=row.preset,
        is_default=False,
    )
