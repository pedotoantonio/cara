"""HA event subscriber — runs as an asyncio task, writes to episodic.

Connects to HA via the adapter's `subscribe_events()`, walks the
async iterator forever, and for each `state_changed` writes a compact
row to the `events` table (episodic memory) so:

  - the diagnostics page can show "last 50 events from HA"
  - reflective batch (Step 8.5) can cluster patterns
  - proactive rules can read "device X has been open for Y minutes"

Reconnect strategy: when the WS stream drops the iterator returns
cleanly. We sleep `RECONNECT_BACKOFF_SECONDS` and reopen, capped at
`RECONNECT_MAX_SECONDS`. No exponential explosion; HA usually comes
back fast.

Conservative payload: we keep `entity_id`, `new_state`, `old_state`,
and a 100-char excerpt of the attributes JSON. Full attributes payload
isn't worth storing for every blink of every motion sensor.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from cara.config import settings


log = structlog.get_logger(__name__)


RECONNECT_BACKOFF_SECONDS = 5.0
RECONNECT_MAX_SECONDS = 60.0


def _truncate_attrs(attrs: dict[str, Any] | None, max_len: int = 200) -> str:
    if not attrs:
        return ""
    try:
        blob = json.dumps(attrs, ensure_ascii=False, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        return ""
    return blob[:max_len]


async def _record_event(sessionmaker: async_sessionmaker, frame: dict[str, Any]) -> None:
    """Persist a state_changed frame to episodic memory."""
    if frame.get("event_type") != "state_changed":
        return
    data = frame.get("data") or {}
    entity_id = data.get("entity_id")
    if not entity_id:
        return

    new_state = data.get("new_state") or {}
    old_state = data.get("old_state") or {}

    payload = {
        "entity_id": entity_id,
        "new": new_state.get("state"),
        "old": old_state.get("state"),
        "attrs": _truncate_attrs(new_state.get("attributes")),
        "fired": frame.get("time_fired"),
    }

    from cara.learning import episodic

    await episodic.record_async(
        kind="ha.state_changed",
        user_id=None,
        ref_id=entity_id,
        outcome="ok",
        payload=payload,
    )


async def run_loop(sessionmaker: async_sessionmaker) -> None:
    """Forever: open WS, drain events, reconnect on drop."""
    log.info("ha_events.start")
    backoff = RECONNECT_BACKOFF_SECONDS
    try:
        while True:
            adapter = await _build_adapter(sessionmaker)
            if adapter is None:
                # HA not configured yet — sleep longer and retry.
                await asyncio.sleep(60.0)
                continue

            try:
                async for frame in adapter.subscribe_events():
                    try:
                        await _record_event(sessionmaker, frame)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("ha_events.record_failed", error=str(exc))
                # iterator returned → connection dropped
                log.info("ha_events.stream_ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("ha_events.subscribe_error", error=str(exc))

            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, RECONNECT_MAX_SECONDS)
    except asyncio.CancelledError:
        log.info("ha_events.stop")
        raise


async def _build_adapter(sessionmaker: async_sessionmaker):
    """Instantiate a fresh adapter from current admin_settings.

    Read settings every loop iteration so the user can swap URL/token
    in admin and the next reconnect picks up the new credentials
    without restarting the backend.
    """
    from cara.services import admin_settings as admin_settings_svc
    from cara.smarthome.homeassistant import HAConfig, HomeAssistantAdapter
    from cara.smarthome.ws_client import ha_ws_factory

    async with sessionmaker() as session:
        enabled = await admin_settings_svc.get(session, "smarthome.enabled")
        if not enabled:
            return None
        url = await admin_settings_svc.get(session, "smarthome.ha_url")
        token = await admin_settings_svc.get(session, "smarthome.ha_token")
    if not url or not token:
        return None
    cfg = HAConfig(base_url=str(url), token=str(token))
    cfg.ws_url = cfg.ws()
    return HomeAssistantAdapter(cfg, ws_factory=ha_ws_factory)  # type: ignore[arg-type]


# avoid unused import warning when settings is referenced elsewhere
_ = settings
