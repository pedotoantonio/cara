"""Production WebSocket factory for the Home Assistant adapter.

Implements the HA WS handshake:

    server: {type: "auth_required", ha_version: ...}
    client: {type: "auth", access_token: "..."}
    server: {type: "auth_ok"}            (or auth_invalid)
    client: {id: 1, type: "subscribe_events", event_type: "state_changed"}
    server: {id: 1, type: "result", success: true}
    server: {id: 1, type: "event", event: {event_type, data, ...}}
    ...

Yields the decoded `event.data` dict (the inner payload) for each
`type: "event"` frame received. Reconnection is the caller's job —
this generator returns when the connection drops or auth fails.

Imports `websockets` lazily so the wider codebase loads without it
(it's a transitive dep via uvicorn but not in our requirements).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import structlog


log = structlog.get_logger(__name__)


async def ha_ws_factory(config) -> AsyncIterator[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Default factory used in production. `config` is HAConfig."""
    from websockets.asyncio.client import connect as ws_connect

    ws_url = getattr(config, "ws_url", None)
    if not ws_url:
        log.warning("ha.ws_factory.no_url")
        return
    token = getattr(config, "token", None)
    if not token:
        log.warning("ha.ws_factory.no_token")
        return

    log.info("ha.ws.connecting", url=str(ws_url))
    try:
        async with ws_connect(str(ws_url)) as ws:
            # 1) auth_required
            first = json.loads(await ws.recv())
            if first.get("type") != "auth_required":
                log.warning("ha.ws.unexpected_first", type=first.get("type"))
                return

            # 2) auth
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            auth_resp = json.loads(await ws.recv())
            if auth_resp.get("type") != "auth_ok":
                log.warning("ha.ws.auth_failed", resp=auth_resp.get("type"))
                return

            log.info("ha.ws.connected")

            # 3) subscribe to state_changed
            await ws.send(json.dumps({
                "id": 1,
                "type": "subscribe_events",
                "event_type": "state_changed",
            }))
            sub_resp = json.loads(await ws.recv())
            if not sub_resp.get("success"):
                log.warning("ha.ws.subscribe_failed", resp=sub_resp)
                return

            # 4) drain
            async for raw in ws:
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if frame.get("type") != "event":
                    continue
                event = frame.get("event") or {}
                # We yield the FULL event, the consumer cares about
                # event_type + data + time_fired.
                yield {
                    "event_type": event.get("event_type"),
                    "data": event.get("data") or {},
                    "time_fired": event.get("time_fired"),
                    "origin": event.get("origin"),
                }
    except Exception as exc:  # noqa: BLE001
        log.warning("ha.ws.error", error=str(exc))
        return
