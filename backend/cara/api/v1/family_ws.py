"""WebSocket endpoint for real-time family sync.

   GET /api/v1/family/ws?token=<jwt>

The WS frame format is the same as `family_bus.publish` produces:
  {"kind": "task.created", "user_id": 1, "payload": {...}}

Auth: JWT passed as query string (browsers can't set headers on the
WebSocket open). We validate using the same helpers as the REST routes.

The handler subscribes to the user's family channel and forwards every
event onto the socket. A disconnect breaks the subscribe loop cleanly.
"""

from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import async_sessionmaker

from cara.services import auth as auth_svc
from cara.services.family_bus import DEFAULT_FAMILY_ID, subscribe
from cara.store import get_sessionmaker


log = structlog.get_logger(__name__)
router = APIRouter()


@router.websocket("/family/ws")
async def family_ws(
    ws: WebSocket,
    token: str = Query(default=""),
) -> None:
    """One WebSocket per browser tab. JWT-auth via ?token= query param."""
    if not token:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Validate JWT using the same helper as REST.
    try:
        claims = auth_svc.decode_token(token)
    except Exception:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if claims.get("type") != "access":
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id = claims.get("sub")
    if not user_id:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept()
    log.info("family_ws.connected", user_id=user_id)

    # Send a welcome frame so the client has a ground truth that the
    # connection is live (vs the browser thinking it succeeded but Redis
    # is down).
    await ws.send_text(json.dumps({
        "kind": "ws.hello",
        "user_id": int(user_id) if str(user_id).isdigit() else user_id,
        "payload": {"channel": DEFAULT_FAMILY_ID},
    }))

    relay_task = asyncio.create_task(_relay(ws))
    keepalive_task = asyncio.create_task(_keepalive(ws))
    try:
        # Drain inbound messages just to detect disconnects.
        while True:
            try:
                await ws.receive_text()
            except WebSocketDisconnect:
                break
    except Exception as exc:  # noqa: BLE001
        log.info("family_ws.error", error=str(exc))
    finally:
        relay_task.cancel()
        keepalive_task.cancel()
        for t in (relay_task, keepalive_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        log.info("family_ws.closed", user_id=user_id)


async def _relay(ws: WebSocket) -> None:
    """Pull events off the family bus and forward to this socket."""
    try:
        async for event in subscribe():
            try:
                await ws.send_text(json.dumps(event, separators=(",", ":")))
            except Exception:  # noqa: BLE001
                # Socket is gone — break the loop, the cleanup happens upstream.
                return
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("family_ws.relay_failed", error=str(exc))


async def _keepalive(ws: WebSocket) -> None:
    """Send a ping every 30 s so proxies don't drop idle connections."""
    try:
        while True:
            await asyncio.sleep(30.0)
            try:
                await ws.send_text(json.dumps({"kind": "ws.ping"}))
            except Exception:  # noqa: BLE001
                return
    except asyncio.CancelledError:
        raise


# Silence the "unused" warning for sessionmaker import — we don't need
# DB access in this endpoint, but importing it ensures startup ordering.
_ = get_sessionmaker
_ = async_sessionmaker
