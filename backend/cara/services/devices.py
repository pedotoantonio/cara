"""Device pairing service.

Pairing flow:

  1. New device boots, has no token. Calls
     POST /api/v1/devices/pair/start → receives 6-digit code + ttl.
  2. Admin browses to /admin/devices, types the code, picks a friendly
     name + surface_class + location → POST /api/v1/devices/pair/finalize.
  3. Backend mints a long-lived device JWT, persists the Device row,
     and stores the JWT against the code in Redis.
  4. New device polls GET /api/v1/devices/pair/status?code=... every
     ~2 s. Once status="paired", it reads the JWT from the response
     and stores it locally.
  5. Subsequent requests use Bearer <device_jwt>; the family-bus WS
     query token also accepts device tokens.

Codes live for 5 minutes in Redis. Both the admin and the new device
need to act before expiry.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.device import (
    DEVICE_STATUS_DISABLED,
    DEVICE_STATUS_ONLINE,
    DEVICE_STATUS_PENDING,
    SURFACE_DESKTOP,
    SURFACE_MOBILE,
    SURFACE_TV,
    SURFACE_WALL,
    SURFACE_WATCH,
    Device,
)
from cara.services import auth as auth_svc

log = structlog.get_logger(__name__)


VALID_SURFACES = {SURFACE_WALL, SURFACE_MOBILE, SURFACE_DESKTOP, SURFACE_WATCH, SURFACE_TV}


# Pairing code lifetime — long enough for the user to walk to the admin
# device, short enough that abandoned codes don't pile up.
PAIR_TTL_SECONDS = 300


# Redis key namespaces.
_REDIS_PAIR_PREFIX = "cara:devices:pair:"


@dataclass
class PairingTicket:
    code: str
    expires_at: datetime
    suggested_name: str | None = None
    suggested_surface: str | None = None


def _generate_code() -> str:
    """6-digit pairing code, zero-padded. ~1M codespace; with 5min TTL +
    rate limiting, brute force is impractical."""
    return f"{secrets.randbelow(10 ** 6):06d}"


async def start_pair(
    redis: Any,
    *,
    suggested_name: str | None = None,
    suggested_surface: str | None = None,
) -> PairingTicket:
    """Create a fresh pairing code. The new device polls
    `pair/status?code=...` until an admin finalises."""
    if redis is None:
        raise RuntimeError("redis required for pairing")

    # Try a few times to avoid an unlikely collision.
    for _ in range(5):
        code = _generate_code()
        key = _REDIS_PAIR_PREFIX + code
        # SETNX-equivalent: only create if not present
        ok = await redis.set(
            key,
            json.dumps({
                "status": "waiting",
                "suggested_name": suggested_name,
                "suggested_surface": suggested_surface,
            }),
            ex=PAIR_TTL_SECONDS,
            nx=True,
        )
        if ok:
            now = datetime.now(timezone.utc)
            from datetime import timedelta
            return PairingTicket(
                code=code,
                expires_at=now + timedelta(seconds=PAIR_TTL_SECONDS),
                suggested_name=suggested_name,
                suggested_surface=suggested_surface,
            )
    raise RuntimeError("could not allocate a pairing code; try again")


async def get_pair_status(redis: Any, code: str) -> dict[str, Any] | None:
    """Read the redis ticket. Returns None if expired / unknown."""
    if redis is None:
        return None
    raw = await redis.get(_REDIS_PAIR_PREFIX + code)
    if not raw:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


async def finalize_pair(
    session: AsyncSession,
    redis: Any,
    *,
    code: str,
    friendly_name: str,
    surface_class: str,
    location: str | None,
    paired_by_user_id: int,
    capabilities: dict[str, Any] | None = None,
) -> Device:
    """Admin call: bind the code to a Device row + mint the JWT.

    Returns the persisted Device. The JWT (column `device_token`) is
    fetched by the device on its next status-poll and never returned via
    the admin endpoint to avoid accidentally exposing it.
    """
    if surface_class not in VALID_SURFACES:
        raise ValueError(f"surface_class invalido: {surface_class}")

    name = (friendly_name or "").strip()
    if not name or len(name) > 80:
        raise ValueError("friendly_name vuoto o troppo lungo")

    ticket = await get_pair_status(redis, code)
    if ticket is None:
        raise ValueError("codice scaduto o non valido")
    if ticket.get("status") != "waiting":
        raise ValueError("codice già usato")

    device = Device(
        friendly_name=name,
        surface_class=surface_class,
        location=(location or None),
        status=DEVICE_STATUS_PENDING,
        enabled=True,
        capabilities=capabilities or {},
        paired_by_user_id=paired_by_user_id,
    )
    session.add(device)
    await session.flush()
    await session.refresh(device)

    token = auth_svc.create_device_token(
        str(device.id),
        extra={"surface": surface_class, "name": name},
    )
    device.device_token = token
    await session.flush()

    # Store the JWT in the redis ticket so the device picks it up.
    await redis.set(
        _REDIS_PAIR_PREFIX + code,
        json.dumps({
            "status": "paired",
            "device_id": str(device.id),
            "friendly_name": name,
            "surface_class": surface_class,
            "device_token": token,
        }),
        ex=PAIR_TTL_SECONDS,  # keep around briefly for the device to pull
    )
    log.info(
        "device.pair.finalized",
        device_id=str(device.id), name=name, surface=surface_class,
        admin_user_id=paired_by_user_id,
    )
    return device


async def consume_pair_token(redis: Any, code: str) -> dict[str, Any] | None:
    """The new device pulls the JWT after the admin paired. Single-use:
    after first read with status=paired, the redis key is deleted so a
    network sniffer can't replay it."""
    ticket = await get_pair_status(redis, code)
    if ticket is None:
        return None
    if ticket.get("status") != "paired":
        return ticket  # still waiting → device should keep polling
    # Hand it off + invalidate.
    await redis.delete(_REDIS_PAIR_PREFIX + code)
    return ticket


# ---------------------------------------------------------------------------
# Admin / management
# ---------------------------------------------------------------------------


async def list_devices(session: AsyncSession) -> list[Device]:
    rows = (
        await session.execute(select(Device).order_by(Device.paired_at.desc()))
    ).scalars().all()
    return list(rows)


async def get_device(session: AsyncSession, device_id: str) -> Device | None:
    import uuid

    try:
        did = uuid.UUID(device_id)
    except ValueError:
        return None
    return await session.get(Device, did)


async def update_device(
    session: AsyncSession,
    device: Device,
    *,
    friendly_name: str | None = None,
    surface_class: str | None = None,
    location: str | None = None,
    enabled: bool | None = None,
) -> Device:
    if friendly_name is not None:
        s = friendly_name.strip()
        if not s or len(s) > 80:
            raise ValueError("friendly_name vuoto o troppo lungo")
        device.friendly_name = s
    if surface_class is not None:
        if surface_class not in VALID_SURFACES:
            raise ValueError(f"surface_class invalido: {surface_class}")
        device.surface_class = surface_class
    if location is not None:
        device.location = location.strip() or None
    if enabled is not None:
        device.enabled = bool(enabled)
        device.status = (
            DEVICE_STATUS_ONLINE if enabled and device.last_seen else
            DEVICE_STATUS_DISABLED if not enabled else
            device.status
        )
    await session.flush()
    return device


async def deauth_device(
    session: AsyncSession, device: Device,
) -> None:
    """Lock the device out: clear device_token + flip status. The next
    request from the device sees its bearer expired (token still valid
    JWT-wise but mismatch with stored row → reject)."""
    device.device_token = None
    device.status = DEVICE_STATUS_DISABLED
    device.enabled = False
    await session.flush()


async def heartbeat(
    session: AsyncSession, device_id: str,
) -> Device | None:
    """Called by paired devices once a minute to mark themselves online."""
    dev = await get_device(session, device_id)
    if dev is None or dev.device_token is None:
        return None
    dev.last_seen = datetime.now(timezone.utc)
    if dev.enabled and dev.status != DEVICE_STATUS_ONLINE:
        dev.status = DEVICE_STATUS_ONLINE
    await session.flush()
    return dev
