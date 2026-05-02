"""CRUD for admin_settings, with typed defaults for known keys.

Keys (and their default values) are declared here so services can read settings
even if no row exists yet — first read returns the default, first write creates
the row.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models import AdminSetting

# Known feature flags. Add to this dict to expose new toggles in the admin UI.
DEFAULTS: dict[str, Any] = {
    "internet_enabled": False,
    "news_enabled": False,
    "video_enabled": False,
    "radio_enabled": False,
    "habit_learning_enabled": False,
    "proactive_suggestions_enabled": False,
    "telegram_bot_enabled": False,
    "facial_recognition_enabled": True,
    "voice_recognition_enabled": True,
    "smart_home_enabled": False,
    "push_notifications_enabled": False,
    "cloud_llm_enabled": False,
    "validation_enabled": False,
    "cognitive_mode": False,
    # Free-form / numeric settings exposed to the admin UI. When unset
    # (None), the runtime falls back to the value from `.env` / `cara.config`.
    "llm_system_prompt": None,
    "llm_max_new_tokens": None,
    "llm_validation_prompt": None,
    "llm_validation_max_tokens": None,
    "llm_cognitive_prompt": None,
    # Voice (TTS) tuning. The browser does the actual synthesis so these
    # are advisory; if `voice_name` doesn't match a voice installed on the
    # device, the frontend falls back to its preferred-Italian heuristic.
    # Numeric ranges follow the SpeechSynthesisUtterance spec.
    "voice_name": None,            # e.g. "Paola"; None = auto-pick best italian
    "voice_rate": None,            # 0.5–2.0 sensible, default 1.0
    "voice_pitch": None,           # 0.0–2.0, default 1.0
    "voice_volume": None,          # 0.0–1.0, default 1.0
    # Content Discovery Agent (CDA) — see /opt/cara/docs/cda-extension-spec.md.
    "cda_enabled": True,           # master switch for the discover tool
    "cda_replace_legacy_pages": False,  # Radio/News pages read from KB when on
    "cda_ytdlp_youtube_enabled": False, # extract YouTube streams via yt-dlp
    "cda_safe_search_for_minors": True, # force safe search for child/teen
    "cda_domain_blacklist": None,  # list[str] of always-blocked domains
    "cda_domain_whitelist_for_child": None,  # allowed domains for child role
}


async def get(session: AsyncSession, key: str) -> Any:
    row = await session.get(AdminSetting, key)
    if row is None:
        return DEFAULTS.get(key)
    return row.value


async def get_with_env_fallback(session: AsyncSession, key: str, env_default: Any) -> Any:
    """Like `get`, but if the stored value is None (or absent), return the
    value passed in (typically from `cara.config.settings.<key>`).

    Use this for prompt/length settings that admins can override at runtime
    without restarting the backend.
    """
    val = await get(session, key)
    if val in (None, ""):
        return env_default
    return val


async def get_all(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(select(AdminSetting))).scalars().all()
    overrides = {r.key: r.value for r in rows}
    return {**DEFAULTS, **overrides}


async def set(
    session: AsyncSession, key: str, value: Any, *, actor_user_id: int | None
) -> AdminSetting:
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting key: {key}")
    row = await session.get(AdminSetting, key)
    if row is None:
        row = AdminSetting(key=key, value=value, updated_by_user_id=actor_user_id)
        session.add(row)
    else:
        row.value = value
        row.updated_by_user_id = actor_user_id
    await session.flush()
    return row
