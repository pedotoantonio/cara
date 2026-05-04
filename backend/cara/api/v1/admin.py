"""Admin panel endpoints — gated by `require_admin`.

Sections (will grow):
- /admin/settings : key-value feature flags (DEFAULTS in services.admin_settings)
- /admin/audit    : recent audit log entries
- /admin/skills   : Skill Factory CRUD + Skill Author trigger (Phase D)
- /admin/users    : list / promote / disable users (TODO)
- /admin/voice    : per-profile TTS knobs (TODO, when Piper is wired)
- /admin/internet : whitelist/blacklist + safe-search (TODO)
- /admin/walls    : registered wall devices (TODO)

Every state-changing endpoint records to the audit log.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import require_admin
from cara.config import settings
from cara.models.skill import Skill
from cara.models.user import User
from cara.services import admin_settings as setting_svc
from cara.services import audit as audit_svc
from cara.skills import author as skill_author
from cara.skills import dispatcher as skill_dispatcher
from cara.store import get_session

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# --- settings -----------------------------------------------------------


class SettingsUpdate(BaseModel):
    """Whatever subset of known keys the admin wants to write."""

    settings: dict[str, Any] = Field(default_factory=dict)


@router.get("/settings", response_model=dict)
async def get_settings(
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    return await setting_svc.get_all(session)


@router.patch("/settings", response_model=dict)
async def patch_settings(
    body: SettingsUpdate,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    changed: dict[str, Any] = {}
    unknown: list[str] = []
    for k, v in body.settings.items():
        try:
            await setting_svc.set(session, k, v, actor_user_id=admin.id)
            changed[k] = v
        except ValueError:
            unknown.append(k)
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"unknown settings: {', '.join(unknown)}"
        )
    if changed:
        await audit_svc.record(
            session,
            actor=admin,
            action="settings.update",
            target_kind="admin_settings",
            detail=changed,
            ip=request.client.host if request.client else None,
        )
    return await setting_svc.get_all(session)


# --- audit --------------------------------------------------------------


class AuditEntry(BaseModel):
    id: str
    actor_email: str | None
    action: str
    target_kind: str | None
    target_id: str | None
    detail: dict | None
    ip: str | None
    note: str | None
    created_at: datetime


@router.get("/audit", response_model=list[AuditEntry])
async def get_audit(
    limit: int = 100,
    action: str | None = None,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[AuditEntry]:
    rows = await audit_svc.list_recent(session, limit=min(limit, 500), action=action)
    return [
        AuditEntry(
            id=str(r.id),
            actor_email=r.actor_email,
            action=r.action,
            target_kind=r.target_kind,
            target_id=r.target_id,
            detail=r.detail,
            ip=r.ip,
            note=r.note,
            created_at=r.created_at,
        )
        for r in rows
    ]


# --- skills (Skill Factory v0.7 — Phase D) -----------------------------


class SkillOut(BaseModel):
    id: str
    name: str
    description: str
    intent_examples: list[str]
    slot_extraction: dict[str, Any]
    plan: dict[str, Any]
    response_template: str | None
    fallback_response: str | None
    status: str
    auto_authored: bool
    version: int
    created_by_user_id: int | None
    approved_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


def _to_out(sk: Skill) -> SkillOut:
    return SkillOut(
        id=str(sk.id),
        name=sk.name,
        description=sk.description,
        intent_examples=list(sk.intent_examples or []),
        slot_extraction=dict(sk.slot_extraction or {}),
        plan=dict(sk.plan or {}),
        response_template=sk.response_template,
        fallback_response=sk.fallback_response,
        status=sk.status,
        auto_authored=sk.auto_authored,
        version=sk.version,
        created_by_user_id=sk.created_by_user_id,
        approved_by_user_id=sk.approved_by_user_id,
        created_at=sk.created_at,
        updated_at=sk.updated_at,
    )


class SkillAuthorRequest(BaseModel):
    user_message: str = Field(..., min_length=3, max_length=2000)
    user_role: str | None = None  # default falls back to admin's own role
    recent_turns: list[str] | None = None
    # Admin can override the user that gets credited as `created_by`
    # (default = the requesting admin themself).
    on_behalf_of_user_id: int | None = None


class SkillAuthorResponse(BaseModel):
    status: str  # "created" | "unsupported"
    skill: SkillOut | None = None
    unsupported: dict[str, Any] | None = None
    telemetry: dict[str, Any]


async def _check_author_rate_limit(
    user_id: int, max_per_day: int, redis_url: str
) -> None:
    """Day-bucket counter in Redis. Fail-open on errors (mirrors CDA pattern)."""
    if max_per_day <= 0:
        return
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return
    try:
        client = aioredis.from_url(redis_url, decode_responses=False)
        from datetime import date

        key = f"skill_author:rl:{user_id}:{date.today().isoformat()}"
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400 + 600)  # 1 day + slack
        results = await pipe.execute()
        count = int(results[0])
        await client.aclose()
    except Exception as exc:  # noqa: BLE001
        log.warning("skill_author.rate_limit.redis_error", error=str(exc))
        return
    if count > max_per_day:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Skill Author rate limit raggiunto ({max_per_day}/giorno).",
        )


@router.post("/skills/author", response_model=SkillAuthorResponse)
async def post_skill_author(
    body: SkillAuthorRequest,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SkillAuthorResponse:
    """Trigger the cloud LLM Skill Author for a single user message.

    On success the proposed skill is persisted as `status='pending'` so the
    admin can review it via GET /admin/skills, then approve/reject.
    On `unsupported` the call is logged but no skill row is created.
    """
    enabled = await setting_svc.get(session, "skill_author_enabled")
    if not enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "skill_author_enabled è OFF (admin flag).",
        )

    if not settings.anthropic_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ANTHROPIC_API_KEY non configurata in .env.",
        )

    # Rate limit per ADMIN (the actual API caller) — covers runaway scripts.
    await _check_author_rate_limit(
        admin.id, settings.skill_author_max_per_day, settings.redis_url
    )

    # Provider/model overrides from admin_settings (fall back to env defaults).
    prompt_override = await setting_svc.get_with_env_fallback(
        session, "skill_author_prompt", None
    )
    provider_override = await setting_svc.get_with_env_fallback(
        session, "skill_author_provider", None
    )
    model_override = await setting_svc.get_with_env_fallback(
        session, "skill_author_model", None
    )

    user_role = body.user_role or admin.role or "parent"
    creator_id = body.on_behalf_of_user_id or admin.id

    t0 = time.perf_counter()
    try:
        proposal, telemetry = await skill_author.author_skill(
            user_message=body.user_message,
            user_role=user_role,
            recent_turns=body.recent_turns,
            prompt_override=prompt_override,
            provider_override=provider_override,
            model_override=model_override,
        )
    except skill_author.SkillAuthorDisabledError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except skill_author.SkillAuthorProviderError as exc:
        await audit_svc.record(
            session, actor=admin, action="skill.author.provider_failed",
            detail={"error": str(exc), "user_message": body.user_message[:300]},
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except skill_author.SkillAuthorValidationError as exc:
        await audit_svc.record(
            session, actor=admin, action="skill.author.validation_failed",
            detail={"reasons": exc.reasons, "raw_preview": exc.raw[:500]},
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Skill Author non ha prodotto JSON valido. Riprova.",
        ) from exc
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    telemetry["elapsed_ms"] = elapsed_ms

    if isinstance(proposal, skill_author.UnsupportedProposal):
        await audit_svc.record(
            session, actor=admin, action="skill.author.unsupported",
            detail={
                "user_message": body.user_message[:300],
                "reason": proposal.reason,
                "missing_primitives": proposal.missing_primitives,
                **telemetry,
            },
            ip=request.client.host if request.client else None,
        )
        return SkillAuthorResponse(
            status="unsupported",
            unsupported={
                "reason": proposal.reason,
                "missing_primitives": proposal.missing_primitives,
            },
            telemetry=telemetry,
        )

    # Validated SkillProposal → persist as pending. Avoid name collision by
    # appending a short uuid suffix if the name is already taken.
    base_name = proposal.name
    name = base_name
    existing = (
        await session.execute(select(Skill.id).where(Skill.name == name))
    ).first()
    if existing is not None:
        name = f"{base_name}_{uuid.uuid4().hex[:6]}"

    sk = Skill(
        name=name,
        description=proposal.description,
        intent_examples=proposal.intent_examples,
        slot_extraction=proposal.slot_extraction,
        plan=proposal.plan,
        response_template=proposal.response_template,
        fallback_response=proposal.fallback_response,
        status="pending",
        auto_authored=True,
        created_by_user_id=creator_id,
    )
    session.add(sk)
    await session.flush()
    await session.refresh(sk)

    await audit_svc.record(
        session, actor=admin, action="skill.author.created",
        target_kind="skill", target_id=str(sk.id),
        detail={
            "name": name,
            "user_message": body.user_message[:300],
            "intent_examples_count": len(proposal.intent_examples),
            "step_count": len(proposal.plan.get("steps") or []),
            **telemetry,
        },
        ip=request.client.host if request.client else None,
    )
    return SkillAuthorResponse(
        status="created", skill=_to_out(sk), telemetry=telemetry
    )


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(
    status_filter: str | None = None,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[SkillOut]:
    stmt = select(Skill).order_by(Skill.created_at.desc())
    if status_filter:
        stmt = stmt.where(Skill.status == status_filter)
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_out(s) for s in rows]


@router.get("/skills/{skill_id}", response_model=SkillOut)
async def get_skill(
    skill_id: uuid.UUID,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SkillOut:
    sk = await session.get(Skill, skill_id)
    if sk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "skill non trovata")
    return _to_out(sk)


@router.post("/skills/{skill_id}/approve", response_model=SkillOut)
async def approve_skill(
    skill_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SkillOut:
    sk = await session.get(Skill, skill_id)
    if sk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "skill non trovata")
    if sk.status == "active":
        return _to_out(sk)
    sk.status = "active"
    sk.approved_by_user_id = admin.id
    await session.flush()
    await session.refresh(sk)
    skill_dispatcher.invalidate_cache()
    await audit_svc.record(
        session, actor=admin, action="skill.approved",
        target_kind="skill", target_id=str(sk.id),
        detail={"name": sk.name, "previous_status": "pending"},
        ip=request.client.host if request.client else None,
    )
    return _to_out(sk)


@router.post("/skills/{skill_id}/reject", response_model=SkillOut)
async def reject_skill(
    skill_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SkillOut:
    sk = await session.get(Skill, skill_id)
    if sk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "skill non trovata")
    prev = sk.status
    sk.status = "disabled"
    await session.flush()
    await session.refresh(sk)
    skill_dispatcher.invalidate_cache()
    await audit_svc.record(
        session, actor=admin, action="skill.rejected",
        target_kind="skill", target_id=str(sk.id),
        detail={"name": sk.name, "previous_status": prev},
        ip=request.client.host if request.client else None,
    )
    return _to_out(sk)


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    sk = await session.get(Skill, skill_id)
    if sk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "skill non trovata")
    name = sk.name
    await session.delete(sk)
    await session.flush()
    skill_dispatcher.invalidate_cache()
    await audit_svc.record(
        session, actor=admin, action="skill.deleted",
        target_kind="skill", target_id=str(skill_id),
        detail={"name": name},
        ip=request.client.host if request.client else None,
    )
