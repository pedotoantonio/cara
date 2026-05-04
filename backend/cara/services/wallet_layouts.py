"""Wallet layout service — CRUD + 4 preset profili (Step 7.4 + 7.5).

Per-(user, surface_class) widget layout. The Wallet rendering endpoint
(`/api/v1/widgets/render?ids=...`) currently takes the id list as a
query parameter; once the frontend has the editor wired, the chain
becomes:

    1. user opens the dashboard
    2. frontend GET /api/v1/wallet/layout?surface=mobile
    3. backend returns the saved item list (or the default if none)
    4. frontend POSTs each widget_id from the list to /widgets/render
    5. user drags/drops to reorder + PUT /wallet/layout

`apply_preset` is the one-click reset: 4 hardcoded layouts the family
picks during onboarding ("Genitore impegnato", "Adolescente",
"Bambino sicuro", "Anziano essenziale"). Each is a list of widget ids
+ default size. The user is encouraged to start from a preset, then
customise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.wallet_layout import WalletLayout


# ---------------------------------------------------------------------------
# Presets — hardcoded so the catalog stays consistent across users
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalletPreset:
    """One canned layout the user can pick during onboarding."""
    slug: str
    label: str                                 # human-readable Italian
    description: str
    items: tuple[dict[str, Any], ...]           # ordered list, like wallet_layout.items


# Each preset is a tuple so it's frozen; the API copies it into the
# user's row as a regular list.
PRESETS: tuple[WalletPreset, ...] = (
    WalletPreset(
        slug="genitore",
        label="Genitore impegnato",
        description=(
            "Tutto quello che serve a un genitore con la giornata piena: "
            "riassunto del giorno, task in scadenza, spesa rapida, "
            "budget mensile, presenza famiglia."
        ),
        items=(
            {"widget_id": "today_summary", "size": "large", "config": {}},
            {"widget_id": "tasks_mine",     "size": "medium", "config": {}},
            {"widget_id": "shopping_quick", "size": "medium", "config": {}},
            {"widget_id": "budget_month",   "size": "medium", "config": {}},
            {"widget_id": "presence",       "size": "small",  "config": {}},
            {"widget_id": "weather_now",    "size": "small",  "config": {}},
            {"widget_id": "quick_actions",  "size": "medium", "config": {}},
        ),
    ),
    WalletPreset(
        slug="teen",
        label="Adolescente",
        description=(
            "Profilo per chi vive di scuola, amici e tempo libero: "
            "task scolastici, meteo, news brevi, radio, frasi del giorno."
        ),
        items=(
            {"widget_id": "tasks_mine",         "size": "medium", "config": {}},
            {"widget_id": "weather_now",        "size": "small",  "config": {}},
            {"widget_id": "news_brief",         "size": "medium", "config": {}},
            {"widget_id": "radio_now_playing",  "size": "small",  "config": {}},
            {"widget_id": "cara_quote",         "size": "small",  "config": {}},
            {"widget_id": "quick_actions",      "size": "medium", "config": {}},
        ),
    ),
    WalletPreset(
        slug="bambino",
        label="Bambino sicuro",
        description=(
            "Schermata semplice e protetta: i compiti, la sua lista, "
            "il meteo e una frase carina al giorno. Niente news, "
            "niente budget, niente smarthome."
        ),
        items=(
            {"widget_id": "kids_homework",  "size": "large",  "config": {}},
            {"widget_id": "tasks_mine",     "size": "medium", "config": {}},
            {"widget_id": "weather_now",    "size": "small",  "config": {}},
            {"widget_id": "cara_quote",     "size": "small",  "config": {}},
        ),
    ),
    WalletPreset(
        slug="anziano",
        label="Anziano essenziale",
        description=(
            "Pochi widget grandi e leggibili: i task del giorno, "
            "il meteo, la radio in ascolto, e chi è in casa. "
            "Niente clutter, niente notifiche."
        ),
        items=(
            {"widget_id": "today_summary",      "size": "large",  "config": {}},
            {"widget_id": "tasks_mine",         "size": "large",  "config": {}},
            {"widget_id": "weather_now",        "size": "medium", "config": {}},
            {"widget_id": "radio_now_playing",  "size": "medium", "config": {}},
            {"widget_id": "presence",           "size": "small",  "config": {}},
        ),
    ),
)


PRESETS_BY_SLUG: dict[str, WalletPreset] = {p.slug: p for p in PRESETS}


# Default fallback when a user has no row yet for a given surface.
# Kept conservative: mostly the same as Genitore but smaller.
_DEFAULT_ITEMS: tuple[dict[str, Any], ...] = (
    {"widget_id": "today_summary",  "size": "medium", "config": {}},
    {"widget_id": "tasks_mine",     "size": "medium", "config": {}},
    {"widget_id": "shopping_quick", "size": "medium", "config": {}},
    {"widget_id": "weather_now",    "size": "small",  "config": {}},
    {"widget_id": "quick_actions",  "size": "small",  "config": {}},
)


_VALID_SURFACES: frozenset[str] = frozenset(
    {"wall", "mobile", "desktop", "watch", "tv"}
)
_VALID_SIZES: frozenset[str] = frozenset({"small", "medium", "large"})


def is_valid_surface(s: str) -> bool:
    return s in _VALID_SURFACES


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def get_layout(
    session: AsyncSession, *, user_id: int, surface_class: str,
) -> WalletLayout | None:
    if surface_class not in _VALID_SURFACES:
        raise ValueError(f"unknown surface_class: {surface_class}")
    return (await session.execute(
        select(WalletLayout).where(
            WalletLayout.user_id == user_id,
            WalletLayout.surface_class == surface_class,
        )
    )).scalar_one_or_none()


async def get_or_default(
    session: AsyncSession, *, user_id: int, surface_class: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Returns `(items, preset_slug)`. When no row exists, returns the
    default layout and `preset_slug=None`."""
    row = await get_layout(session, user_id=user_id, surface_class=surface_class)
    if row is None:
        return list(_DEFAULT_ITEMS), None
    return list(row.items), row.preset


def _validate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanity check + normalise the items list.

    Drops malformed rows; clamps unknown sizes to "medium". Caps the
    layout at 32 widgets (a generous upper bound that keeps the
    rendering endpoint within its 32-widget cap).
    """
    cleaned: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        wid = entry.get("widget_id")
        if not isinstance(wid, str) or not wid.strip():
            continue
        if wid in seen_ids:
            continue          # collapse duplicates — last write wins implicitly
        seen_ids.add(wid)
        size = entry.get("size", "medium")
        if size not in _VALID_SIZES:
            size = "medium"
        config = entry.get("config", {})
        if not isinstance(config, dict):
            config = {}
        cleaned.append({"widget_id": wid, "size": size, "config": config})
        if len(cleaned) >= 32:
            break
    return cleaned


async def upsert_layout(
    session: AsyncSession,
    *,
    user_id: int,
    surface_class: str,
    items: list[dict[str, Any]],
    preset: str | None = "custom",
    commit: bool = False,
) -> WalletLayout:
    """Replace the user's layout for `surface_class`.

    `preset` defaults to `"custom"` because any explicit edit detaches
    the layout from a preset. To set a preset, use `apply_preset`.
    """
    if surface_class not in _VALID_SURFACES:
        raise ValueError(f"unknown surface_class: {surface_class}")
    cleaned = _validate_items(items)

    row = await get_layout(session, user_id=user_id, surface_class=surface_class)
    if row is None:
        row = WalletLayout(
            user_id=user_id, surface_class=surface_class,
            items=cleaned, preset=preset,
        )
        session.add(row)
    else:
        row.items = cleaned
        row.preset = preset
    await session.flush()
    if commit:
        await session.commit()
    return row


async def apply_preset(
    session: AsyncSession,
    *,
    user_id: int,
    surface_class: str,
    preset_slug: str,
    commit: bool = False,
) -> WalletLayout:
    """One-click apply: copy the preset's items into the user's row."""
    preset = PRESETS_BY_SLUG.get(preset_slug)
    if preset is None:
        raise ValueError(f"unknown preset: {preset_slug}")
    return await upsert_layout(
        session,
        user_id=user_id, surface_class=surface_class,
        items=[dict(it) for it in preset.items],
        preset=preset_slug,
        commit=commit,
    )


async def reset_layout(
    session: AsyncSession,
    *,
    user_id: int,
    surface_class: str,
    commit: bool = False,
) -> bool:
    """Drop the user's row → next read returns the default layout."""
    row = await get_layout(session, user_id=user_id, surface_class=surface_class)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    if commit:
        await session.commit()
    return True
