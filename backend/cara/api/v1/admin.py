"""Admin panel endpoints — gated by `require_admin`.

Sections (will grow):
- /admin/settings : key-value feature flags (DEFAULTS in services.admin_settings)
- /admin/audit    : recent audit log entries
- /admin/users    : list / promote / disable users (TODO)
- /admin/voice    : per-profile TTS knobs (TODO, when Piper is wired)
- /admin/internet : whitelist/blacklist + safe-search (TODO)
- /admin/walls    : registered wall devices (TODO)

Every state-changing endpoint records to the audit log.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import require_admin
from cara.models.user import User
from cara.services import admin_settings as setting_svc
from cara.services import audit as audit_svc
from cara.store import get_session

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
