"""Server-Sent Events endpoint.

Streams every event emitted on the in-process EventBus to subscribed
clients. The frontend HomePage uses this to drive the Edo expression
bridge, the state caption, and (future) wake-word indicator.

Wire format (SSE):

    event: <bus_event_name>
    data: <json payload>

A `state_changed` event arrives whenever the StateMachine transitions:

    event: state_changed
    data: {"from": "idle", "to": "thinking"}

A wildcard subscriber drains all events; clients that only care about
state can filter on `event: state_changed`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from cara.api.deps import get_current_user
from cara.core import LumoState, get_bus, get_state_machine
from cara.models.user import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["events"])


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


@router.get("/events/stream")
async def events_stream(
    user: User = Depends(get_current_user),  # noqa: B008
) -> StreamingResponse:
    """Authenticated SSE channel — one queue per connection.

    The bus has a process-global wildcard subscriber that pushes events
    into this connection's queue. The queue is drained by the async
    generator below and serialised as SSE frames.
    """
    bus = get_bus()
    sm = get_state_machine()
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=200)

    def _on_event(payload: dict[str, Any]) -> None:
        # The wildcard subscriber receives `payload` only — it doesn't see
        # the event name. We grab it from the bus emission via a tiny
        # closure over the dispatch site instead. Simpler: re-emit through
        # a typed wrapper. Since the wildcard handler in EventBus loses
        # the event name, we register one handler per known event below.
        pass  # placeholder, replaced by per-event registration below

    # Per-event handlers — we know the names because they're emitted by
    # backend code we control. Registering by name preserves the event tag
    # in the SSE stream.
    KNOWN_EVENTS = (
        "state_changed",
        "chat.noise_bypass",
        "chat.routed.start",
        "chat.routed.done",
        "chat.llm.start",
        "chat.llm.first_token",
        "chat.llm.done",
        "cda.discovery.start",
        "cda.discovery.cached_hit",
        "cda.discovery.success",
        "cda.discovery.failed",
    )

    handlers: list[tuple[str, Any]] = []

    def _make_handler(evt: str) -> Any:
        def handler(payload: dict[str, Any]) -> None:
            try:
                queue.put_nowait((evt, payload))
            except asyncio.QueueFull:
                logger.warning("events.stream.queue_full", event=evt)
        return handler

    for evt in KNOWN_EVENTS:
        h = _make_handler(evt)
        bus.on(evt, h)
        handlers.append((evt, h))

    async def _generator() -> AsyncIterator[bytes]:
        # Send the current state on connect so the client doesn't have to
        # wait for the next transition to render correctly.
        yield _sse(
            "snapshot",
            {"state": sm.state.value, "user_id": user.id},
        )
        # Heartbeat every 25s so proxies don't close the connection.
        try:
            while True:
                try:
                    evt, payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield _sse(evt, payload)
                except asyncio.TimeoutError:
                    yield b": ping\n\n"
        finally:
            for evt, h in handlers:
                bus.off(evt, h)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/events/state")
async def events_state(
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """One-shot snapshot of the current StateMachine state.

    Useful for clients that don't want to keep a long-lived SSE open
    (e.g. a status badge that polls every 10 s).
    """
    sm = get_state_machine()
    return {
        "state": sm.state.value,
        "valid_states": [s.value for s in LumoState],
        "user_id": user.id,
    }
