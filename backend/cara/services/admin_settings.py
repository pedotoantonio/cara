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
    # Per-family TTS pronunciation overrides on top of the shipped
    # anglicisms.yaml. Dict[str, str] = {english_word: italian_phonetic}.
    # An empty-string value deletes the corresponding base-dictionary
    # entry. Hot-swap by the TTSNormalizer the next time the chat layer
    # re-syncs (which happens on every TTS request).
    "tts_user_overrides": {},
    # TTS streaming chunked (Step 1.3). When true, chat() splits the LLM
    # output at sentence boundaries and emits SSE `audio_chunk` events
    # alongside `token` events — first audio plays in ~2s instead of
    # waiting for the full response. Disabled by default until the
    # frontend WebAudio queue is wired.
    "tts_streaming_enabled": False,
    # Content Discovery Agent (CDA) — see /opt/cara/docs/cda-extension-spec.md.
    "cda_enabled": True,           # master switch for the discover tool
    "cda_replace_legacy_pages": False,  # Radio/News pages read from KB when on
    "cda_ytdlp_youtube_enabled": False, # extract YouTube streams via yt-dlp
    "cda_safe_search_for_minors": True, # force safe search for child/teen
    "cda_domain_blacklist": None,  # list[str] of always-blocked domains
    "cda_domain_whitelist_for_child": None,  # allowed domains for child role
    "cda_agent_loop_enabled": True,  # forced grounding on info-need queries
    # Persona tone preset (Lumo-inspired). Layered ON TOP of llm_system_prompt:
    #   "default"  → persona standard, contesto storico + profilo utente
    #   "privacy"  → no profilo utente, no cronologia, solo turno corrente
    #   "playful"  → persona più scherzosa, no profilo nel prompt
    "tone_preset": "default",
    # Hot-swappable LLM size variant. "fast" = 1.5B (~9 tok/s), "quality" =
    # 3B (~4 tok/s, less hallucination). Switch is destroy+load (~10 s).
    "llm_quality_mode": "fast",
    # Skill Factory v0.7 — Phase D (Skill Author).
    # Master switch. When OFF, /admin/skills/author returns 503 even if the
    # ANTHROPIC_API_KEY is set — gives the admin a one-click kill switch.
    "skill_author_enabled": False,
    # Free-form override of the system prompt used to brief the cloud LLM.
    # None → use the default in cara.skills.author.DEFAULT_AUTHOR_PROMPT.
    "skill_author_prompt": None,
    # Override of the provider/model. None → fall back to env-set
    # SKILL_AUTHOR_PROVIDER / SKILL_AUTHOR_MODEL. Useful to flip Haiku ↔ Sonnet
    # at runtime without redeploy.
    "skill_author_provider": None,
    "skill_author_model": None,
    # Skill Factory dispatcher tiers (Phase C).
    #   tier-1 = regex (always on, free)
    #   tier-2 = cosine over intent_examples embeddings (~50ms, on by default
    #            once the embedder is loaded)
    #   tier-3 = local 1.5B LLM classifier ("which skill, if any, fits?")
    #            ~500ms-2s on the NPU. Off by default — flip on when you want
    #            CARA to learn aggressively from chat misses.
    "skill_dispatcher_tier2_enabled": True,
    "skill_dispatcher_tier3_enabled": False,
    # Confidence threshold for tier-2 cosine. Below this, the message is
    # considered NOT a match and we fall through to tier-3 / LLM.
    "skill_dispatcher_tier2_threshold": 0.65,
    # First-run setup wizard — opaque dict the wizard backend uses to
    # persist its progress (current_step, completed_steps, env_dirty,
    # cert_fingerprint, ...). The frontend reads this from /setup/status.
    "setup_state": None,
    # Identity / locale.
    "timezone": "Europe/Rome",
    "language": "it",
    # Family identity (NER glossary + display name).
    "family_name": None,
    "family_glossary": None,
    "family_size": None,
    # Family residence — used by the weather intent + future location-aware
    # widgets (sunrise/sunset, daylight, push reminders timed to commute).
    # `family_city` is a free-text label shown in the UI; the lat/lon are
    # resolved via `WeatherService.geocode()` when the admin saves the city
    # and stored alongside it. Empty / None → no weather replies, the chat
    # layer says "imposta la città in /admin/impostazioni".
    "family_city": None,            # e.g. "Torino"
    "family_country": "IT",         # ISO 3166-1 alpha-2
    "family_lat": None,             # float, geocoded from family_city
    "family_lon": None,             # float, geocoded from family_city
    # HomeAssistant adapter (used when smart_home_enabled=True).
    "ha_url": None,
    "ha_token": None,
    # Frigate NVR + frigate-faces (referenced by widgets + presence).
    # When None, the runtime falls back to `cara.config.settings`
    # (`http://frigate:5000`, `http://frigate-faces:5051`).
    "frigate_url": None,
    "frigate_faces_url": None,
    # Per-camera overrides, keyed by Frigate camera id (e.g. "cam_194").
    # Each entry: {"label": "Ingresso", "area": "ingresso",
    #              "presence_relevant": True, "notify_motion": False}.
    # The actual camera list is read live from Frigate's /api/config; this
    # dict only stores CARA-specific metadata (display label, area binding
    # for smart-home presence triggers, whether the camera should count
    # toward "chi è in casa", whether to push Telegram on motion).
    # Discoverable / editable via `/api/v1/admin/cameras` (admin-only).
    "cameras": {},
    # Window (minutes) used by the motion-fallback path: when no recognised
    # face was seen recently we still tell the user "vedo movimento" if
    # Frigate had a `person` event within this window.
    "presence_motion_window_minutes": 30,
    # Password-less login for clients on the home LAN or WireGuard VPN
    # (192.168.1.0/24, 10.8.0.0/24, 127.0.0.0/8). When True, the
    # frontend's POST /api/v1/auth/lan-login returns a JWT for the
    # first admin without prompting for credentials. Public-internet
    # access (Cloudflare Tunnel, port forward) is unaffected. Flip to
    # False if you later want to enforce credential auth even at home.
    "lan_auto_login_enabled": True,
    # Presence agent — face arrivals via frigate-faces poll.
    "presence_greeting_enabled": True,
    "presence_greeting_cooldown_min_known": 30,
    "presence_greeting_cooldown_min_unknown": 5,
    "presence_greeting_silent_hours": [22, 8],     # local Europe/Rome
    "presence_push_enabled": True,
    # Notification dispatcher — per-channel master switches.
    "notify_telegram_enabled": True,
    "notify_push_enabled": True,
    "notify_ws_tts_enabled": True,
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
