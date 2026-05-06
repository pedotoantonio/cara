"""First-run setup wizard backend.

The wizard walks a brand-new admin through CARA configuration without
ever asking them to open a terminal. See
`docs/first-run-setup-wizard-prompt.md` for the full spec.

Routes are split between:

  - **Anonymous**: `GET /setup/status`, `POST /setup/admin` (only fires
    when no admin exists yet).
  - **Admin-gated**: every other endpoint, called by the in-progress
    wizard after Step 1 has minted the admin's JWT.

Persistence model:

  `users` row             — Step 1 admin
  `admin_settings`        — every flag/preset (family, voice, llm,
                            feature flags, integrations on/off);
                            the wizard's own progress lives here under
                            the synthetic key `setup_state` (a dict).
  `.env` via env_writer   — secrets that pydantic-settings reads at
                            backend boot (VAPID, Google OAuth,
                            ANTHROPIC_API_KEY, JWT_SECRET, etc.).
                            Mutating the .env requires a backend
                            restart, surfaced as a banner in the UI.

The wizard is idempotent: re-running it doesn't reset existing values
unless the admin explicitly overwrites them.
"""

from __future__ import annotations

import os
import secrets as _secrets
import shutil
import subprocess
import uuid
from datetime import datetime
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_session, require_admin
from cara.models.user import User
from cara.services import admin_settings
from cara.services import audit as audit_svc
from cara.services import auth as auth_svc
from cara.services.env_writer import mask_secret, read_env, write_env

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])


# ---------------------------------------------------------------------------
# Setup state — stored as `admin_settings["setup_state"]` (a dict).
# ---------------------------------------------------------------------------


SETUP_STATE_KEY = "setup_state"
SETUP_VERSION = 1
DEFAULT_STEPS = (
    "admin", "tls", "family", "voice", "llm",
    "integrations", "google_cloud", "feature_flags",
)


async def _get_setup_state(session: AsyncSession) -> dict[str, Any]:
    raw = await admin_settings.get(session, SETUP_STATE_KEY)
    if isinstance(raw, dict):
        return raw
    return {
        "completed": False,
        "current_step": "admin",
        "version": SETUP_VERSION,
        "completed_steps": [],
        "completed_at": None,
        "completed_by_user_id": None,
    }


async def _save_setup_state(
    session: AsyncSession,
    state: dict[str, Any],
    *,
    actor_user_id: int | None = None,
) -> None:
    await admin_settings.set(
        session, SETUP_STATE_KEY, state, actor_user_id=actor_user_id,
    )


async def _mark_step_completed(
    session: AsyncSession,
    step: str,
    *,
    actor_user_id: int | None,
) -> dict[str, Any]:
    state = await _get_setup_state(session)
    completed = list(state.get("completed_steps", []))
    if step not in completed:
        completed.append(step)
    state["completed_steps"] = completed
    # Advance current_step to the next un-completed step
    for s in DEFAULT_STEPS:
        if s not in completed:
            state["current_step"] = s
            break
    else:
        state["current_step"] = "complete"
    await _save_setup_state(session, state, actor_user_id=actor_user_id)
    return state


async def _admin_exists(session: AsyncSession) -> bool:
    stmt = select(User).where(User.is_admin.is_(True), User.is_active.is_(True))
    return (await session.execute(stmt)).first() is not None


# ---------------------------------------------------------------------------
# Status (anonymous)
# ---------------------------------------------------------------------------


class SetupStatus(BaseModel):
    completed: bool
    current_step: str
    version: int
    completed_steps: list[str]
    has_admin: bool
    needs_restart: bool   # true if .env was mutated since last container boot
    steps: list[str]


@router.get("/status", response_model=SetupStatus)
async def setup_status(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SetupStatus:
    state = await _get_setup_state(session)
    has_admin = await _admin_exists(session)
    return SetupStatus(
        completed=bool(state.get("completed", False)),
        current_step=state.get("current_step", "admin"),
        version=state.get("version", SETUP_VERSION),
        completed_steps=list(state.get("completed_steps", [])),
        has_admin=has_admin,
        needs_restart=bool(state.get("env_dirty", False)),
        steps=list(DEFAULT_STEPS),
    )


# ---------------------------------------------------------------------------
# Step 1 — Admin (anonymous, single-shot)
# ---------------------------------------------------------------------------


class AdminCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    full_name: str = Field(min_length=1, max_length=120)
    birth_date: str | None = None     # ISO YYYY-MM-DD, optional
    timezone: str = Field(default="Europe/Rome", max_length=64)


class AdminCreateResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: int
    email: str


@router.post(
    "/admin", response_model=AdminCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def setup_admin(
    body: AdminCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AdminCreateResponse:
    """Anonymous endpoint: creates the very first admin user.

    Refuses with 403 if any active admin already exists, or if the
    setup_state is already marked completed. After success, mints a
    JWT pair so the wizard's UI authenticates seamlessly into the
    next step.
    """
    state = await _get_setup_state(session)
    if state.get("completed"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "setup già completato",
        )
    if await _admin_exists(session):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "esiste già un amministratore",
        )

    # Email lower-case + uniqueness gate
    email = body.email.lower()
    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        # Promote the existing user to admin instead of failing.
        existing.is_admin = True
        existing.is_active = True
        existing.full_name = body.full_name
        existing.password_hash = auth_svc.hash_password(body.password)
        if body.birth_date:
            from datetime import date as _date
            try:
                existing.birth_date = _date.fromisoformat(body.birth_date)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"data nascita non valida: {exc}",
                ) from exc
        admin_user = existing
    else:
        admin_user = User(
            email=email,
            full_name=body.full_name,
            password_hash=auth_svc.hash_password(body.password),
            is_admin=True,
            is_active=True,
            role="parent",
        )
        if body.birth_date:
            from datetime import date as _date
            try:
                admin_user.birth_date = _date.fromisoformat(body.birth_date)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"data nascita non valida: {exc}",
                ) from exc
        session.add(admin_user)
    await session.flush()
    await session.refresh(admin_user)

    # Save timezone in admin_settings so the proactivity engine
    # reads it consistently.
    await admin_settings.set(
        session, "timezone", body.timezone, actor_user_id=admin_user.id,
    )

    state = await _get_setup_state(session)
    state.setdefault("completed_steps", [])
    if "admin" not in state["completed_steps"]:
        state["completed_steps"].append("admin")
    state["current_step"] = "tls"
    await _save_setup_state(session, state, actor_user_id=admin_user.id)

    await audit_svc.record(
        session, actor=admin_user, action="setup.step.admin",
        target_kind="user", target_id=str(admin_user.id),
        detail={"email": email, "promoted": existing is not None},
        ip=request.client.host if request.client else None,
    )
    await session.commit()

    return AdminCreateResponse(
        access_token=auth_svc.create_access_token(
            admin_user.id, extra={"is_admin": True},
        ),
        refresh_token=auth_svc.create_refresh_token(admin_user.id),
        user_id=admin_user.id,
        email=admin_user.email,
    )


# ---------------------------------------------------------------------------
# Step 2 — TLS (admin-gated)
# ---------------------------------------------------------------------------


class TLSRegenerateRequest(BaseModel):
    extra_hosts: list[str] | None = None  # additional SAN entries


class TLSRegenerateResponse(BaseModel):
    fingerprint_sha256: str
    san: list[str]
    expires_at: str
    ca_url: str


@router.post("/cert/regenerate", response_model=TLSRegenerateResponse)
async def cert_regenerate(
    body: TLSRegenerateRequest,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TLSRegenerateResponse:
    """Generate a fresh mkcert-signed cert covering 192.168.1.23 +
    common LAN aliases + any additional hosts the admin requested.

    The mkcert binary lives on the HOST (not in the container) and was
    set up during the v1.0 sprint (see CHANGELOG.md). Inside the
    container we just verify the binary exists at /usr/local/bin/mkcert
    via subprocess and call it; the host file system is bind-mounted
    into the container at /host-mkcert when this endpoint is wanted —
    if not mounted, the endpoint returns 503 and asks the admin to run
    the regeneration manually with the runbook in MANUALE-ADMIN.md.
    """
    mkcert = shutil.which("mkcert")
    if mkcert is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "mkcert non disponibile in container — usa il runbook in "
            "docs/MANUALE-ADMIN.md per rigenerare il cert manualmente",
        )

    # Default SAN list. Caller may add more (e.g. their own domain).
    base_hosts = [
        "192.168.1.23",
        "10.8.0.1",
        "127.0.0.1",
        "localhost",
        "nanopc-t6",
        "nanopc-t6.local",
        "nanopc-t6.station",
        "cara.home.lan",
        "cara.local",
    ]
    extra = [h.strip() for h in (body.extra_hosts or []) if h.strip()]
    san = base_hosts + extra

    out_dir = "/tmp/cara-cert"
    os.makedirs(out_dir, exist_ok=True)
    crt = f"{out_dir}/server.crt"
    key = f"{out_dir}/server.key"
    try:
        proc = subprocess.run(
            [
                mkcert, "-cert-file", crt, "-key-file", key,
                *san,
            ],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, "mkcert timeout",
        ) from exc
    if proc.returncode != 0:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"mkcert ha fallito: {proc.stderr[:200]}",
        )

    # Compute fingerprint via openssl (always available on the runtime image).
    try:
        fp_proc = subprocess.run(
            ["openssl", "x509", "-in", crt, "-noout", "-fingerprint", "-sha256"],
            capture_output=True, text=True, timeout=5,
        )
        fingerprint = (fp_proc.stdout or "").split("=", 1)[-1].strip()
    except Exception:  # noqa: BLE001
        fingerprint = ""

    # Compute notAfter date.
    try:
        date_proc = subprocess.run(
            ["openssl", "x509", "-in", crt, "-noout", "-enddate"],
            capture_output=True, text=True, timeout=5,
        )
        expires_at = (date_proc.stdout or "").split("=", 1)[-1].strip()
    except Exception:  # noqa: BLE001
        expires_at = ""

    state = await _get_setup_state(session)
    state["cert_fingerprint"] = fingerprint
    await _save_setup_state(session, state, actor_user_id=admin.id)
    await _mark_step_completed(session, "tls", actor_user_id=admin.id)

    await audit_svc.record(
        session, actor=admin, action="setup.step.tls",
        target_kind="cert", target_id=fingerprint[:32] or "regen",
        detail={"san": san, "fingerprint": fingerprint},
        ip=request.client.host if request.client else None,
    )
    await session.commit()

    log.info("setup.cert.regenerated", san=san, fingerprint=fingerprint)
    return TLSRegenerateResponse(
        fingerprint_sha256=fingerprint,
        san=san,
        expires_at=expires_at,
        ca_url="http://192.168.1.23/cara-ca.crt",
    )


@router.post("/cert/skip")
async def cert_skip(
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    """Mark the TLS step skipped (admin chose to keep self-signed)."""
    await _mark_step_completed(session, "tls", actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.step.tls.skipped",
        target_kind="cert", target_id="skip",
        detail={},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return {"status": "skipped"}


# ---------------------------------------------------------------------------
# Step 3 — Family identity
# ---------------------------------------------------------------------------


class FamilySettings(BaseModel):
    family_name: str = Field(max_length=80)
    glossary: list[str] = Field(default_factory=list, max_length=64)
    family_size: int = Field(default=4, ge=1, le=12)
    language: str = Field(default="it", max_length=8)


@router.post("/family")
async def setup_family(
    body: FamilySettings,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    payload = {
        "family_name": body.family_name.strip(),
        "family_glossary": [s.strip() for s in body.glossary if s.strip()][:64],
        "family_size": body.family_size,
        "language": body.language,
    }
    for k, v in payload.items():
        try:
            await admin_settings.set(session, k, v, actor_user_id=admin.id)
        except ValueError:
            # Key not in DEFAULTS — register on the fly via raw insert.
            from cara.models.admin_setting import AdminSetting
            row = await session.get(AdminSetting, k)
            if row is None:
                row = AdminSetting(key=k, value=v, updated_by_user_id=admin.id)
                session.add(row)
            else:
                row.value = v
                row.updated_by_user_id = admin.id

    await _mark_step_completed(session, "family", actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.step.family",
        target_kind="settings", target_id="family",
        detail=payload,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return payload


# ---------------------------------------------------------------------------
# Step 4 — Voice
# ---------------------------------------------------------------------------


class VoiceSettings(BaseModel):
    voice_name: str | None = None
    voice_rate: float | None = Field(default=None, ge=0.5, le=2.0)
    voice_pitch: float | None = Field(default=None, ge=0.0, le=2.0)
    voice_volume: float | None = Field(default=None, ge=0.0, le=1.0)
    wake_word_enabled: bool = False
    tts_streaming_enabled: bool = True


@router.post("/voice")
async def setup_voice(
    body: VoiceSettings,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    payload = body.model_dump(exclude_unset=True)
    if "voice_name" in payload:
        await admin_settings.set(session, "voice_name", payload["voice_name"], actor_user_id=admin.id)
    if "voice_rate" in payload:
        await admin_settings.set(session, "voice_rate", payload["voice_rate"], actor_user_id=admin.id)
    if "voice_pitch" in payload:
        await admin_settings.set(session, "voice_pitch", payload["voice_pitch"], actor_user_id=admin.id)
    if "voice_volume" in payload:
        await admin_settings.set(session, "voice_volume", payload["voice_volume"], actor_user_id=admin.id)
    if "tts_streaming_enabled" in payload:
        await admin_settings.set(
            session, "tts_streaming_enabled",
            bool(payload["tts_streaming_enabled"]), actor_user_id=admin.id,
        )

    # wake_word_enabled is per-device pref; stored as default for new devices.
    state = await _get_setup_state(session)
    state["wake_word_default"] = bool(body.wake_word_enabled)
    await _save_setup_state(session, state, actor_user_id=admin.id)

    await _mark_step_completed(session, "voice", actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.step.voice",
        target_kind="settings", target_id="voice",
        detail=payload,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return payload


# ---------------------------------------------------------------------------
# Step 5 — LLM
# ---------------------------------------------------------------------------


class LLMSettings(BaseModel):
    quality_mode: str = Field(default="fast", pattern="^(fast|quality)$")
    tone_preset: str = Field(default="default", pattern="^(default|privacy|playful)$")
    max_new_tokens: int = Field(default=512, ge=64, le=1024)
    system_prompt: str | None = Field(default=None, max_length=4000)
    validation_enabled: bool = False
    cognitive_mode: bool = False


@router.post("/llm")
async def setup_llm(
    body: LLMSettings,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    await admin_settings.set(session, "llm_quality_mode", body.quality_mode, actor_user_id=admin.id)
    await admin_settings.set(session, "tone_preset", body.tone_preset, actor_user_id=admin.id)
    await admin_settings.set(session, "llm_max_new_tokens", body.max_new_tokens, actor_user_id=admin.id)
    if body.system_prompt is not None:
        await admin_settings.set(session, "llm_system_prompt", body.system_prompt, actor_user_id=admin.id)
    await admin_settings.set(session, "validation_enabled", body.validation_enabled, actor_user_id=admin.id)
    await admin_settings.set(session, "cognitive_mode", body.cognitive_mode, actor_user_id=admin.id)

    # Flush the KV cache so the new prompt prefix takes effect.
    try:
        from cara.ai import kv_cache
        kv_cache.flush_all()
    except Exception as exc:  # noqa: BLE001
        log.debug("setup.llm.kv_flush_failed", error=str(exc))

    await _mark_step_completed(session, "llm", actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.step.llm",
        target_kind="settings", target_id="llm",
        detail=body.model_dump(),
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return body.model_dump()


# ---------------------------------------------------------------------------
# Step 6 — Integrations (HA, Frigate, VAPID, Telegram)
# ---------------------------------------------------------------------------


class HASettings(BaseModel):
    enabled: bool = True
    url: str = Field(default="http://172.31.0.1:8123", max_length=200)
    token: str | None = None  # plaintext on input; stored encrypted upstream


class HATestRequest(BaseModel):
    url: str
    token: str


@router.post("/homeassistant/test")
async def homeassistant_test(
    body: HATestRequest,
    _admin: User = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    """Probe call: hits HA's /api/states and counts entities."""
    headers = {"Authorization": f"Bearer {body.token}"}
    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            r = await client.get(f"{body.url.rstrip('/')}/api/states", headers=headers)
        if r.status_code == 401:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token HA non valido")
        if r.status_code >= 400:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"HA ha risposto {r.status_code}",
            )
        data = r.json()
        return {"ok": True, "entity_count": len(data) if isinstance(data, list) else 0}
    except httpx.RequestError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"impossibile contattare HA: {exc}",
        ) from exc


@router.post("/homeassistant")
async def setup_homeassistant(
    body: HASettings,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    await admin_settings.set(
        session, "smart_home_enabled", body.enabled, actor_user_id=admin.id,
    )
    if body.token:
        # Persist as plaintext in admin_settings — sensitive but localhost
        # only. Future hardening: encrypt with OAUTH_ENCRYPTION_KEY.
        from cara.models.admin_setting import AdminSetting
        for key, value in (("ha_url", body.url), ("ha_token", body.token)):
            row = await session.get(AdminSetting, key)
            if row is None:
                row = AdminSetting(key=key, value=value, updated_by_user_id=admin.id)
                session.add(row)
            else:
                row.value = value
                row.updated_by_user_id = admin.id
    await audit_svc.record(
        session, actor=admin, action="setup.step.integrations.ha",
        target_kind="settings", target_id="ha",
        detail={"url": body.url, "token": mask_secret(body.token), "enabled": body.enabled},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return {"ok": True}


class VAPIDGenerateResponse(BaseModel):
    public_key: str
    private_key_set: bool


@router.post("/vapid/generate", response_model=VAPIDGenerateResponse)
async def vapid_generate(
    body: dict | None = None,
    request: Request = None,  # type: ignore[assignment]
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> VAPIDGenerateResponse:
    """Generate a VAPID keypair, write it to .env, return the public key."""
    subject = (body or {}).get("subject") or f"mailto:{admin.email}"
    try:
        from py_vapid import Vapid01
        v = Vapid01()
        v.generate_keys()
        priv = v.private_key_pem().decode("utf-8") if hasattr(v, "private_key_pem") else None
        # Newer pywebpush expects raw base64 keys, not PEM. Fall back if missing.
        if priv is None or not hasattr(v, "public_key"):
            raise RuntimeError("py_vapid API mismatch — install pywebpush>=2")
        public_b64 = v.public_key  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"generazione VAPID fallita: {exc}",
        ) from exc

    write_env({
        "VAPID_PUBLIC_KEY": str(public_b64),
        "VAPID_PRIVATE_KEY": priv,
        "VAPID_SUBJECT": subject,
    })

    state = await _get_setup_state(session)
    state["env_dirty"] = True
    await _save_setup_state(session, state, actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.step.integrations.vapid",
        target_kind="settings", target_id="vapid",
        detail={"public_key_prefix": str(public_b64)[:16], "subject": subject},
        ip=request.client.host if request.client else None,
    )
    await session.commit()

    return VAPIDGenerateResponse(public_key=str(public_b64), private_key_set=True)


class TelegramSettings(BaseModel):
    enabled: bool = False
    bot_token: str | None = None
    allowed_chat_ids: list[str] = Field(default_factory=list)


@router.post("/telegram")
async def setup_telegram(
    body: TelegramSettings,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    await admin_settings.set(
        session, "telegram_bot_enabled", body.enabled, actor_user_id=admin.id,
    )
    if body.bot_token:
        write_env({
            "CARA_TELEGRAM_BOT_TOKEN": body.bot_token,
            "CARA_TELEGRAM_ALLOWED_CHAT_IDS": ",".join(body.allowed_chat_ids),
        })
        state = await _get_setup_state(session)
        state["env_dirty"] = True
        await _save_setup_state(session, state, actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.step.integrations.telegram",
        target_kind="settings", target_id="telegram",
        detail={
            "enabled": body.enabled,
            "bot_token": mask_secret(body.bot_token),
            "allowed_chats": len(body.allowed_chat_ids),
        },
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return {"ok": True}


@router.post("/integrations/complete")
async def integrations_complete(
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Mark the integrations step finished — called after the admin
    has saved/skipped each of the four integration cards."""
    await _mark_step_completed(session, "integrations", actor_user_id=admin.id)
    await session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Step 7 — Google + Cloud
# ---------------------------------------------------------------------------


class GoogleSettings(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    generate_encryption_key: bool = False


@router.post("/google")
async def setup_google(
    body: GoogleSettings,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    updates: dict[str, str] = {}
    if body.client_id:
        updates["GOOGLE_OAUTH_CLIENT_ID"] = body.client_id
    if body.client_secret:
        updates["GOOGLE_OAUTH_CLIENT_SECRET"] = body.client_secret
    if body.generate_encryption_key:
        # Only generate if not already present.
        existing = read_env().get("OAUTH_ENCRYPTION_KEY", "").strip()
        if not existing:
            updates["OAUTH_ENCRYPTION_KEY"] = _secrets.token_hex(32)
    if updates:
        write_env(updates)
        state = await _get_setup_state(session)
        state["env_dirty"] = True
        await _save_setup_state(session, state, actor_user_id=admin.id)

    await audit_svc.record(
        session, actor=admin, action="setup.step.google",
        target_kind="settings", target_id="google",
        detail={k: mask_secret(v) for k, v in updates.items()},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return {"ok": True, "wrote_keys": sorted(updates.keys())}


class CloudSettings(BaseModel):
    enabled: bool = False
    api_key: str | None = None
    skill_author_enabled: bool = False


@router.post("/cloud/test")
async def cloud_test(
    body: CloudSettings,
    _admin: User = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    """Tiny probe call to confirm the API key works without spending
    real tokens (uses the count_tokens endpoint, free tier safe)."""
    if not body.api_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "api_key vuota")
    headers = {
        "x-api-key": body.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {"model": "claude-haiku-4-5", "messages": [{"role": "user", "content": "ping"}]}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages/count_tokens",
                headers=headers, json=payload,
            )
        if r.status_code == 401:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key non valida")
        if r.status_code >= 400:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Anthropic ha risposto {r.status_code}: {r.text[:200]}",
            )
        return {"ok": True, "input_tokens": r.json().get("input_tokens", 0)}
    except httpx.RequestError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"impossibile contattare Anthropic: {exc}",
        ) from exc


@router.post("/cloud")
async def setup_cloud(
    body: CloudSettings,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    await admin_settings.set(
        session, "cloud_llm_enabled", body.enabled, actor_user_id=admin.id,
    )
    await admin_settings.set(
        session, "skill_author_enabled",
        body.enabled and body.skill_author_enabled,
        actor_user_id=admin.id,
    )
    if body.api_key:
        write_env({"ANTHROPIC_API_KEY": body.api_key})
        state = await _get_setup_state(session)
        state["env_dirty"] = True
        await _save_setup_state(session, state, actor_user_id=admin.id)
    await _mark_step_completed(session, "google_cloud", actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.step.cloud",
        target_kind="settings", target_id="cloud",
        detail={
            "enabled": body.enabled,
            "skill_author_enabled": body.skill_author_enabled,
            "api_key": mask_secret(body.api_key),
        },
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Step 8 — Feature flags + complete
# ---------------------------------------------------------------------------


class FeatureFlags(BaseModel):
    internet_enabled: bool = False
    news_enabled: bool = False
    radio_enabled: bool = False
    cda_enabled: bool = True
    cda_safe_search_for_minors: bool = True
    proactive_suggestions_enabled: bool = False
    habit_learning_enabled: bool = False
    skill_dispatcher_tier2_enabled: bool = True
    skill_dispatcher_tier3_enabled: bool = False
    voice_recognition_enabled: bool = True


@router.post("/feature-flags")
async def setup_feature_flags(
    body: FeatureFlags,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    payload = body.model_dump()
    for key, value in payload.items():
        try:
            await admin_settings.set(session, key, value, actor_user_id=admin.id)
        except ValueError:
            log.warning("setup.feature_flags.unknown_key", key=key)
    await _mark_step_completed(session, "feature_flags", actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.step.feature_flags",
        target_kind="settings", target_id="flags",
        detail=payload,
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return payload


@router.post("/complete")
async def setup_complete(
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    state = await _get_setup_state(session)
    state["completed"] = True
    state["completed_at"] = datetime.utcnow().isoformat() + "Z"
    state["completed_by_user_id"] = admin.id
    state["current_step"] = "complete"
    await _save_setup_state(session, state, actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.completed",
        target_kind="setup", target_id="v1",
        detail={"completed_steps": state.get("completed_steps", [])},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return {"ok": True, "needs_restart": bool(state.get("env_dirty", False))}


@router.post("/reset")
async def setup_reset(
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Re-open the wizard for an existing admin (does NOT delete data
    or revoke users)."""
    state = await _get_setup_state(session)
    state["completed"] = False
    state["current_step"] = "admin"
    state["completed_steps"] = list(set(state.get("completed_steps", [])) - {"admin"})
    await _save_setup_state(session, state, actor_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="setup.reset",
        target_kind="setup", target_id="v1",
        detail={},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return {"ok": True}
