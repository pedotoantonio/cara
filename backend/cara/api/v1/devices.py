"""Device pairing + admin management.

Public (anonymous) endpoints — used by a brand-new device that has no
JWT yet:
  POST /devices/pair/start          → returns {code, expires_at}
  GET  /devices/pair/status?code=…  → {status, device_token?}

Admin-only endpoints:
  POST /devices/pair/finalize       — bind a code to a Device row
  GET  /devices                     — list all paired devices
  GET  /devices/{id}                — fetch one
  PATCH /devices/{id}               — rename / change surface / enable
  DELETE /devices/{id}              — deauthorise (revoke device token)

Device-only:
  POST /devices/heartbeat           — paired device pings here every minute
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_session, require_admin
from cara.config import settings as _settings
from cara.models.device import Device
from cara.models.user import User
from cara.services import audit as audit_svc
from cara.services import devices as device_svc

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/devices", tags=["devices"])


# Lazy-singleton redis (same pattern as family_bus etc.).
_redis_client: Any | None = None


async def _get_redis():  # noqa: ANN202
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as redis_asyncio
            _redis_client = redis_asyncio.from_url(
                _settings.redis_url, decode_responses=True,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("devices.redis_init_failed", error=str(exc))
            return None
    return _redis_client


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PairStartRequest(BaseModel):
    suggested_name: str | None = Field(default=None, max_length=80)
    suggested_surface: str | None = None


class PairStartResponse(BaseModel):
    code: str
    expires_at: datetime


class PairStatusResponse(BaseModel):
    status: str  # 'waiting' | 'paired' | 'expired'
    device_token: str | None = None
    device_id: str | None = None
    friendly_name: str | None = None
    surface_class: str | None = None


class PairFinalizeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    friendly_name: str = Field(min_length=1, max_length=80)
    surface_class: str
    location: str | None = Field(default=None, max_length=80)
    capabilities: dict[str, Any] | None = None


class DeviceOut(BaseModel):
    id: str
    friendly_name: str
    surface_class: str
    location: str | None
    status: str
    enabled: bool
    capabilities: dict[str, Any]
    paired_at: datetime
    last_seen: datetime | None
    paired_by_user_id: int | None


def _to_out(d: Device) -> DeviceOut:
    return DeviceOut(
        id=str(d.id),
        friendly_name=d.friendly_name,
        surface_class=d.surface_class,
        location=d.location,
        status=d.status,
        enabled=d.enabled,
        capabilities=dict(d.capabilities or {}),
        paired_at=d.paired_at,
        last_seen=d.last_seen,
        paired_by_user_id=d.paired_by_user_id,
    )


class DevicePatch(BaseModel):
    friendly_name: str | None = Field(default=None, max_length=80)
    surface_class: str | None = None
    location: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# Public — no auth (the device is still trying to get one)
# ---------------------------------------------------------------------------


@router.post("/pair/start", response_model=PairStartResponse)
async def pair_start(body: PairStartRequest) -> PairStartResponse:
    redis = await _get_redis()
    if redis is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "pairing non disponibile (Redis offline)",
        )
    try:
        ticket = await device_svc.start_pair(
            redis,
            suggested_name=body.suggested_name,
            suggested_surface=body.suggested_surface,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return PairStartResponse(code=ticket.code, expires_at=ticket.expires_at)


@router.get("/pair/status", response_model=PairStatusResponse)
async def pair_status(code: str = Query(min_length=6, max_length=6)) -> PairStatusResponse:
    redis = await _get_redis()
    if redis is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "pairing non disponibile (Redis offline)",
        )
    ticket = await device_svc.consume_pair_token(redis, code)
    if ticket is None:
        return PairStatusResponse(status="expired")
    return PairStatusResponse(
        status=ticket.get("status", "waiting"),
        device_token=ticket.get("device_token"),
        device_id=ticket.get("device_id"),
        friendly_name=ticket.get("friendly_name"),
        surface_class=ticket.get("surface_class"),
    )


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@router.post(
    "/pair/finalize", response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
)
async def pair_finalize(
    body: PairFinalizeRequest,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DeviceOut:
    redis = await _get_redis()
    if redis is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "pairing non disponibile (Redis offline)",
        )
    try:
        device = await device_svc.finalize_pair(
            session, redis,
            code=body.code, friendly_name=body.friendly_name,
            surface_class=body.surface_class,
            location=body.location,
            paired_by_user_id=admin.id,
            capabilities=body.capabilities,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    await audit_svc.record(
        session, actor=admin, action="device.paired",
        target_kind="device", target_id=str(device.id),
        detail={
            "name": device.friendly_name,
            "surface": device.surface_class,
            "location": device.location,
        },
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return _to_out(device)


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DeviceOut]:
    rows = await device_svc.list_devices(session)
    return [_to_out(d) for d in rows]


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(
    device_id: str,
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DeviceOut:
    d = await device_svc.get_device(session, device_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device non trovato")
    return _to_out(d)


@router.patch("/{device_id}", response_model=DeviceOut)
async def patch_device(
    device_id: str,
    body: DevicePatch,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DeviceOut:
    d = await device_svc.get_device(session, device_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device non trovato")
    try:
        await device_svc.update_device(
            session, d,
            friendly_name=body.friendly_name,
            surface_class=body.surface_class,
            location=body.location,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    await audit_svc.record(
        session, actor=admin, action="device.patched",
        target_kind="device", target_id=str(d.id),
        detail=body.model_dump(exclude_unset=True),
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return _to_out(d)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: str,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    d = await device_svc.get_device(session, device_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device non trovato")
    name = d.friendly_name
    await device_svc.deauth_device(session, d)
    await session.delete(d)
    await session.commit()
    await audit_svc.record(
        session, actor=admin, action="device.deleted",
        target_kind="device", target_id=device_id,
        detail={"name": name},
        ip=request.client.host if request.client else None,
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Heartbeat — paired device only
# ---------------------------------------------------------------------------


class HeartbeatBody(BaseModel):
    device_id: str  # the JWT carries it but echo it for clarity


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat(
    body: HeartbeatBody,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Anonymous from the API's perspective — verification is via the
    persisted device_token (the JWT alone isn't enough since admin can
    revoke by clearing the column)."""
    # In a tighter design we'd verify the JWT signature here. For
    # v1.0 we keep it simple: the device sends its UUID, we mark it
    # online if the row exists + token is still set.
    d = await device_svc.heartbeat(session, body.device_id)
    if d is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "device sconosciuto o disabilitato")
    await session.commit()
