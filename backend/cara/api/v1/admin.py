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
from cara.skills import primitives as _skill_primitives  # noqa: F401 — register on import
from cara.skills.registry import list_primitives as _list_primitives
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
        # Settings that change the LLM prefix (system prompt, tone)
        # invalidate every cached KV-cache file: the saved prefill is
        # tied to the previous prefix and would feed the model the wrong
        # context. Cheap to flush — every active conversation just pays
        # one turn of normal TTFT (~200ms) on its next message.
        if any(k in changed for k in ("llm_system_prompt", "tone")):
            from cara.ai import kv_cache

            removed = kv_cache.flush_all()
            if removed:
                log.info("admin.kv_cache.flushed_after_prompt_change",
                         removed=removed, keys=list(changed.keys()))
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


# --- memory admin (per-user fact governance) --------------------------
#
# The plain `/api/v1/memory/*` routes are scoped to the current user.
# Admins also need a way to inspect (and, in extreme cases, purge) the
# memory of another family member — typically to debug a hallucinated
# fact or honour a delete request from a household member who can't
# operate their own account (kid, elder).
#
# All endpoints under /admin/memory are gated by `require_admin` and
# log to audit so the action is traceable.


@router.get("/memory/users")
async def list_users_with_facts(
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict]:
    """Roster of users with their fact counts (active vs total)."""
    from sqlalchemy import case, func, select as _select

    from cara.models.fact import Fact
    from cara.models.user import User as _U

    rows = (
        await session.execute(
            _select(
                _U.id, _U.email, _U.full_name, _U.role,
                func.count(Fact.id).label("total"),
                func.sum(case((Fact.active.is_(True), 1), else_=0)).label("active"),
            )
            .join(Fact, Fact.user_id == _U.id, isouter=True)
            .group_by(_U.id, _U.email, _U.full_name, _U.role)
            .order_by(_U.email)
        )
    ).all()
    out: list[dict] = []
    for r in rows:
        out.append({
            "user_id": r.id,
            "email": r.email,
            "full_name": r.full_name,
            "role": r.role,
            "facts_total": int(r.total or 0),
            "facts_active": int(r.active or 0),
        })
    return out


@router.get("/memory/{target_user_id}/facts")
async def list_user_facts_admin(
    target_user_id: int,
    active_only: bool = False,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict]:
    """Admin view of facts owned by `target_user_id`."""
    from cara.learning import semantic
    rows = await semantic.list_facts(
        session, user_id=target_user_id,
        active_only=active_only, limit=500,
    )
    return [
        {
            "id": f.id,
            "user_id": f.user_id,
            "type": f.type,
            "text": f.text,
            "source": f.source,
            "confidence": f.confidence,
            "first_seen": f.first_seen.isoformat(),
            "last_confirmed": f.last_confirmed.isoformat(),
            "expiry": f.expiry.isoformat() if f.expiry else None,
            "active": f.active,
        }
        for f in rows
    ]


@router.delete("/memory/{target_user_id}/facts/{fact_id}", status_code=204)
async def deactivate_user_fact_admin(
    target_user_id: int,
    fact_id: int,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Admin soft-delete (active=False) of a single fact for any user."""
    from sqlalchemy import select as _select

    from cara.models.fact import Fact

    fact = (
        await session.execute(
            _select(Fact).where(
                Fact.id == fact_id, Fact.user_id == target_user_id,
            )
        )
    ).scalar_one_or_none()
    if fact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fact not found")
    fact.active = False
    await audit_svc.record(
        session, actor=admin, action="memory.fact.deactivated",
        target_kind="fact", target_id=str(fact.id),
        detail={"target_user_id": target_user_id, "text": fact.text[:120]},
        ip=request.client.host if request.client else None,
    )
    await session.commit()


@router.post("/memory/{target_user_id}/purge")
async def purge_user_memory_admin(
    target_user_id: int,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, int]:
    """Hard-delete every fact owned by `target_user_id`. Audit-logged."""
    from sqlalchemy import delete as _delete

    from cara.models.fact import Fact

    res = await session.execute(
        _delete(Fact).where(Fact.user_id == target_user_id)
    )
    deleted = res.rowcount or 0
    await audit_svc.record(
        session, actor=admin, action="memory.purge",
        target_kind="user", target_id=str(target_user_id),
        detail={"deleted": deleted},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return {"deleted": deleted}


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


# --- Skill manual edit + primitive catalog (Phase E) -------------------


class SkillPatch(BaseModel):
    """Whole-document edit. Any field omitted is left untouched.

    `intent_examples`, `slot_extraction`, `plan`, `response_template`,
    `fallback_response`, `description` can be hand-edited from the
    admin UI. `name` is intentionally not patchable (used as cache
    key by the dispatcher); rename = create a new skill instead.
    """

    description: str | None = None
    intent_examples: list[str] | None = None
    slot_extraction: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    response_template: str | None = None
    fallback_response: str | None = None


@router.patch("/skills/{skill_id}", response_model=SkillOut)
async def patch_skill(
    skill_id: uuid.UUID,
    body: SkillPatch,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SkillOut:
    sk = await session.get(Skill, skill_id)
    if sk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "skill non trovata")

    changes: dict[str, Any] = {}
    if body.description is not None:
        sk.description = body.description.strip()
        changes["description"] = True
    if body.intent_examples is not None:
        # cap to 32 examples to keep prompt budget under control
        sk.intent_examples = list(body.intent_examples)[:32]
        changes["intent_examples"] = len(sk.intent_examples)
    if body.slot_extraction is not None:
        sk.slot_extraction = dict(body.slot_extraction)
        changes["slot_extraction"] = True
    if body.plan is not None:
        # minimal validation: must have steps:list
        steps = body.plan.get("steps") if isinstance(body.plan, dict) else None
        if not isinstance(steps, list) or not steps:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "plan.steps deve essere una lista non vuota",
            )
        # validate each step references a known primitive
        for i, step in enumerate(steps):
            if not isinstance(step, dict) or not step.get("tool"):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"step[{i}] manca del campo 'tool'",
                )
            from cara.skills.registry import get_primitive
            if get_primitive(step["tool"]) is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"step[{i}].tool {step['tool']!r} non è una primitive registrata",
                )
        sk.plan = dict(body.plan)
        changes["plan"] = True
    if body.response_template is not None:
        sk.response_template = body.response_template
        changes["response_template"] = True
    if body.fallback_response is not None:
        sk.fallback_response = body.fallback_response
        changes["fallback_response"] = True

    if not changes:
        return _to_out(sk)

    sk.version = (sk.version or 1) + 1
    await session.flush()
    await session.refresh(sk)
    skill_dispatcher.invalidate_cache()

    await audit_svc.record(
        session, actor=admin, action="skill.patched",
        target_kind="skill", target_id=str(sk.id),
        detail={"name": sk.name, "changes": changes, "version": sk.version},
        ip=request.client.host if request.client else None,
    )
    return _to_out(sk)


class PrimitiveOut(BaseModel):
    name: str
    description: str
    args_schema: dict[str, str]
    returns_schema: dict[str, str]
    needs_session: bool
    needs_user_id: bool


@router.get("/skills/primitives/catalog", response_model=list[PrimitiveOut])
async def primitive_catalog(
    _admin: User = Depends(require_admin),  # noqa: B008
) -> list[PrimitiveOut]:
    """Catalog of primitives the JSON editor can reference. Useful as
    an inline help panel when editing a skill plan."""
    return [
        PrimitiveOut(
            name=p.name,
            description=p.description,
            args_schema=p.args_schema,
            returns_schema=p.returns_schema,
            needs_session=p.needs_session,
            needs_user_id=p.needs_user_id,
        )
        for p in _list_primitives()
    ]
