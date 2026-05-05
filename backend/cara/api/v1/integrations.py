"""User-facing integrations endpoints (settings page).

  GET    /api/v1/integrations              → list of my connections
  GET    /api/v1/integrations/calendars    → google calendars (R-only)
  POST   /api/v1/integrations/{id}/config  → set calendar_id, direction, …
  DELETE /api/v1/integrations/{id}         → disconnect (revoke + drop)
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.integrations import google_calendar as gcal
from cara.integrations import google_oauth
from cara.models.oauth_credentials import OAuthCredentials
from cara.models.user import User
from cara.store import get_session


log = structlog.get_logger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("")
async def list_my_integrations(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(OAuthCredentials)
            .where(OAuthCredentials.user_id == user.id)
            .order_by(OAuthCredentials.created_at)
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "provider": r.provider,
            "scope_set": r.scope_set,
            "account_email": r.account_email,
            "config": r.config_json,
            "revoked": r.revoked,
            "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/calendars")
async def list_my_calendars(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, Any]]:
    """Return the user's available Google calendars so the UI can
    show a picker. Requires an active calendar:rw connection."""
    cred = (
        await session.execute(
            select(OAuthCredentials)
            .where(OAuthCredentials.user_id == user.id)
            .where(OAuthCredentials.provider == "google")
            .where(OAuthCredentials.scope_set == "calendar:rw")
            .where(OAuthCredentials.revoked.is_(False))
        )
    ).scalar_one_or_none()
    if cred is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Calendar non collegato. Connetti prima il tuo Google account.",
        )
    try:
        token = await google_oauth.get_access_token(session, cred)
        cals = await gcal.list_calendars(token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Google API error: {exc}",
        ) from exc
    return cals


class IntegrationConfigBody(BaseModel):
    calendar_id: str | None = None       # which calendar to sync
    push_enabled: bool | None = None     # also write tasks back to Google


@router.post("/{integration_id}/config")
async def set_integration_config(
    integration_id: int,
    body: IntegrationConfigBody,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    cred = await session.get(OAuthCredentials, integration_id)
    if cred is None or cred.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "integration not found")
    cfg: dict[str, Any] = dict(cred.config_json or {})
    if body.calendar_id is not None:
        cfg["calendar_id"] = body.calendar_id
        # Reset sync_token so the next pull sees the full window.
        cfg.pop("sync_token", None)
    if body.push_enabled is not None:
        cfg["push_enabled"] = bool(body.push_enabled)
    cred.config_json = cfg
    await session.commit()
    return {"id": cred.id, "config": cfg}


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_integration(
    integration_id: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    cred = await session.get(OAuthCredentials, integration_id)
    if cred is None or cred.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "integration not found")
    try:
        await google_oauth.revoke_credentials(session, cred)
    except Exception as exc:  # noqa: BLE001
        log.warning("integrations.revoke_failed", error=str(exc))
        # Even if Google revoke failed, drop the row.
        await session.delete(cred)
        await session.commit()
