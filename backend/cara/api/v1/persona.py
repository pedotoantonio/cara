"""Persona profile REST endpoints — self-service + admin.

Lumo-conversion Ondata β.

Two surfaces:

  GET    /api/v1/persona/me           → my profile (any authed user)
  POST   /api/v1/persona/me/rebuild   → rebuild mine right now (rate-limited)
  DELETE /api/v1/persona/me           → wipe mine (GDPR Art. 17)

  GET    /api/v1/admin/persona/{user_id}          → see anyone's profile
  PATCH  /api/v1/admin/persona/{user_id}          → manual override of MD
  POST   /api/v1/admin/persona/{user_id}/rebuild  → trigger rebuild
  DELETE /api/v1/admin/persona/{user_id}          → wipe

Admin endpoints record to the audit log; self-service endpoints don't
(it's your own data).

Rate limit on self-service rebuild: at most one per user per 30 min.
Rebuilds are CPU/NPU-intensive (~30s per chunk × N chunks) and could
DoS the chat. The admin endpoint is unthrottled.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai import get_llm_service
from cara.api.deps import get_current_user, require_admin
from cara.learning import persona_profiler
from cara.models import PersonaProfile, User
from cara.services import audit as audit_svc
from cara.store import get_session


log = structlog.get_logger(__name__)

router = APIRouter(tags=["persona"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PersonaOut(BaseModel):
    user_id: int
    markdown: str
    confidence: float | None
    sections: dict[str, Any] | None
    last_status: str | None
    last_error: str | None
    last_built_at: datetime | None
    last_message_id_consumed: int | None


class PersonaPatch(BaseModel):
    """Admin manual override of the profile Markdown."""
    markdown: str = Field(..., max_length=12000)
    confidence: float | None = Field(None, ge=0, le=100)


class RebuildOut(BaseModel):
    status: str
    chunks_processed: int = 0
    messages_consumed: int = 0
    confidence: float | None = None
    markdown_chars: int = 0
    error: str | None = None


def _to_out(p: PersonaProfile) -> PersonaOut:
    return PersonaOut(
        user_id=p.user_id,
        markdown=p.markdown or "",
        confidence=p.confidence,
        sections=p.sections,
        last_status=p.last_status,
        last_error=p.last_error,
        last_built_at=p.last_built_at,
        last_message_id_consumed=p.last_message_id_consumed,
    )


# ---------------------------------------------------------------------------
# Self-service
# ---------------------------------------------------------------------------


@router.get("/persona/me", response_model=PersonaOut | None)
async def get_my_persona(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PersonaOut | None:
    profile = await session.get(PersonaProfile, user.id)
    return _to_out(profile) if profile else None


# In-memory rebuild rate-limiter. Per-process: when uvicorn workers > 1,
# you could in theory rebuild twice in parallel, but the LLM lock would
# serialise anyway. Keeping it lightweight; switch to Redis when needed.
_LAST_REBUILD_AT: dict[int, datetime] = {}
_MIN_REBUILD_INTERVAL = timedelta(minutes=30)


async def _do_rebuild(user_id: int) -> RebuildOut:
    """Async background runner — gets its own session + LLM handle.

    Returns the rebuild result (also persists it). Logs in case the
    caller dropped the response.
    """
    from cara.store import get_sessionmaker  # noqa: PLC0415
    Session = get_sessionmaker()
    llm = get_llm_service()
    if llm is None:
        return RebuildOut(status="failed", error="llm not available")
    async with Session() as session:
        result = await persona_profiler.rebuild_for_user(session, llm, user_id)
        await session.commit()
    return RebuildOut(**result)


@router.post("/persona/me/rebuild", response_model=RebuildOut)
async def rebuild_my_persona(
    background: BackgroundTasks,
    user: User = Depends(get_current_user),  # noqa: B008
) -> RebuildOut:
    """Rebuild MY profile NOW.

    Returns 202-ish (status='queued') if the rebuild is long; the
    client polls GET /persona/me to see the result. We don't run it
    inline because EXTRACT/MERGE can take 30s per user and that's
    way over the HTTP timeout for a typical client.
    """
    now = datetime.now(timezone.utc)
    last = _LAST_REBUILD_AT.get(user.id)
    if last is not None and (now - last) < _MIN_REBUILD_INTERVAL:
        wait = int((_MIN_REBUILD_INTERVAL - (now - last)).total_seconds())
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"already rebuilt recently — retry in {wait}s",
        )
    _LAST_REBUILD_AT[user.id] = now

    # Fire-and-forget. Returns immediately.
    async def _runner() -> None:
        try:
            await _do_rebuild(user.id)
        except Exception:  # noqa: BLE001
            log.exception("persona.rebuild.background_failed", user_id=user.id)
    asyncio.create_task(_runner())

    return RebuildOut(status="queued")


@router.delete("/persona/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_persona(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """GDPR Art. 17 — right to erasure for the profile."""
    profile = await session.get(PersonaProfile, user.id)
    if profile is not None:
        await session.delete(profile)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@router.get("/admin/persona/{user_id}", response_model=PersonaOut | None)
async def admin_get_persona(
    user_id: int,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PersonaOut | None:
    profile = await session.get(PersonaProfile, user_id)
    return _to_out(profile) if profile else None


@router.patch("/admin/persona/{user_id}", response_model=PersonaOut)
async def admin_patch_persona(
    user_id: int,
    body: PersonaPatch,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PersonaOut:
    """Manual edit of the profile Markdown — for when the nightly
    rebuild produced something wrong / incomplete and the admin wants
    to correct it. Sections are reparsed automatically."""
    profile = await session.get(PersonaProfile, user_id)
    if profile is None:
        # Allow creating via PATCH — the watermark stays NULL so the
        # next nightly rebuild starts from scratch and MERGEs with this.
        profile = PersonaProfile(user_id=user_id, markdown=body.markdown)
        session.add(profile)
    else:
        profile.markdown = body.markdown
    if body.confidence is not None:
        profile.confidence = body.confidence
    profile.sections = persona_profiler._parse_sections(body.markdown)  # noqa: SLF001
    profile.last_status = "ok"
    profile.last_error = None
    profile.updated_at = datetime.now(timezone.utc)
    session.add(profile)
    await session.flush()

    await audit_svc.record(
        session,
        actor=admin,
        action="persona.patch",
        target_kind="persona_profile",
        target_id=str(user_id),
        detail={
            "markdown_chars": len(body.markdown),
            "confidence": body.confidence,
        },
        ip=request.client.host if request.client else None,
    )
    return _to_out(profile)


@router.post("/admin/persona/{user_id}/rebuild", response_model=RebuildOut)
async def admin_rebuild_persona(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RebuildOut:
    """Trigger a rebuild NOW for any user (no rate limit).

    Runs in the foreground so the admin gets the result. May take
    1-3 minutes for a user with no prior profile and a long history."""
    await audit_svc.record(
        session,
        actor=admin,
        action="persona.rebuild",
        target_kind="persona_profile",
        target_id=str(user_id),
        ip=request.client.host if request.client else None,
    )
    await session.commit()  # write audit before the long LLM run

    llm = get_llm_service()
    if llm is None:
        return RebuildOut(status="failed", error="llm not available")

    result = await persona_profiler.rebuild_for_user(session, llm, user_id)
    await session.commit()
    return RebuildOut(**result)


@router.delete(
    "/admin/persona/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_persona(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Wipe a user's profile. Audited."""
    profile = await session.get(PersonaProfile, user_id)
    if profile is not None:
        await session.delete(profile)
    await audit_svc.record(
        session,
        actor=admin,
        action="persona.delete",
        target_kind="persona_profile",
        target_id=str(user_id),
        ip=request.client.host if request.client else None,
    )
