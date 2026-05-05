"""Family event bus — Redis pub/sub fan-out for real-time UI sync.

When a user adds/edits/deletes a task on phone A, every other browser
in the family should see the change without a manual refresh. Same for
shopping, notes, appointments.

Architecture:

  HTTP handler (e.g. POST /api/v1/tasks)
        │
        ├── persists to Postgres
        └── publishes a small JSON event to Redis channel
            "cara:family:{family_id}"

  Each connected WebSocket on /ws/family/{id} subscribes to the same
  channel and re-broadcasts the event to its socket. Browsers receive,
  React stores reconcile, UI updates.

  Today the family ID is constant ("default") — the project is
  single-household for now. When/if multi-tenant arrives, this is the
  one place to swap in a real family_id from the user row.

The bus is fire-and-forget: a publish failure is logged and dropped.
We never block a HTTP request waiting on Redis.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Final

import structlog

from cara.config import settings


log = structlog.get_logger(__name__)

# For the foreseeable future the project is single-household. The channel
# key is parameterised so swapping later costs nothing.
DEFAULT_FAMILY_ID: Final = "default"


def channel_for(family_id: str) -> str:
    return f"cara:family:{family_id}"


_redis_client = None  # type: ignore[var-annotated]


async def _get_redis():  # noqa: ANN202
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as redis_asyncio
        _redis_client = redis_asyncio.from_url(
            settings.redis_url, decode_responses=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("family_bus.redis_init_failed", error=str(exc))
        _redis_client = None
    return _redis_client


async def publish(
    kind: str,
    *,
    family_id: str = DEFAULT_FAMILY_ID,
    user_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget publish to the family channel.

    `kind`: dot-namespaced event type ("task.created", "task.updated",
    "task.deleted", "shopping.created", "note.deleted", …).
    `user_id`: who triggered it; clients can dim their own events to
    avoid the local-echo flicker.
    `payload`: small dict (we cap at 4 KB to keep Redis happy).
    """
    msg = {
        "kind": kind,
        "user_id": user_id,
        "payload": payload or {},
    }
    try:
        body = json.dumps(msg, separators=(",", ":"))
    except Exception as exc:  # noqa: BLE001
        log.warning("family_bus.serialize_failed", kind=kind, error=str(exc))
        return
    if len(body) > 4096:
        log.warning("family_bus.payload_too_big", kind=kind, size=len(body))
        return

    client = await _get_redis()
    if client is None:
        return
    try:
        await client.publish(channel_for(family_id), body)
    except Exception as exc:  # noqa: BLE001
        log.warning("family_bus.publish_failed", kind=kind, error=str(exc))


async def subscribe(family_id: str = DEFAULT_FAMILY_ID):  # type: ignore[no-untyped-def]
    """Async generator — yields decoded JSON dicts as they arrive.

    Caller is responsible for dropping the generator on disconnect; we
    handle Redis reconnects internally with a 2 s backoff.
    """
    while True:
        client = await _get_redis()
        if client is None:
            await asyncio.sleep(2.0)
            continue
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(channel_for(family_id))
            log.info("family_bus.subscribed", family_id=family_id)
            try:
                async for raw in pubsub.listen():
                    if not isinstance(raw, dict):
                        continue
                    if raw.get("type") != "message":
                        continue
                    data = raw.get("data")
                    if not data:
                        continue
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue
            finally:
                try:
                    await pubsub.unsubscribe(channel_for(family_id))
                    await pubsub.close()
                except Exception:  # noqa: BLE001
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("family_bus.listen_error", error=str(exc))
            await asyncio.sleep(2.0)
