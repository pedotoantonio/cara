"""Unified notification dispatcher — single entry point that fans out
a logical event to every active channel: Telegram, Web Push (VAPID),
WebSocket family-bus (so the wallet / live caption can react), and
optional Piper TTS for vocal greetings.

Why a single dispatcher: every callsite — presence agent, proactivity
rules, agent failure handler, calendar reminders, whatever comes next —
should be able to fire-and-forget a `Notification` and trust that the
right channels light up. Per-channel knobs live in admin_settings so
the family can mute Telegram-only or push-only without code changes.

Each channel is best-effort: a failure on one (Telegram down, push
unsubscribed) never blocks the others. Failures log a warning and
write a `notify.failed` event for diagnostics.
"""

from __future__ import annotations

import asyncio
import structlog
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from cara.services import admin_settings as _admin


log = structlog.get_logger(__name__)


@dataclass(slots=True)
class Notification:
    """One thing CARA wants to tell someone.

    Most callsites only set `kind`, `title`, `body`. Everything else
    has sensible defaults. The `tag` is the dedupe key on the OS push
    layer + the Telegram inline-button group.
    """

    kind: str                                  # "presence.arrival" / "proactivity.morning" / "agent.failed"
    title: str                                 # short — phone notification headline
    body: str                                  # one-paragraph human text
    tag: str | None = None                     # dedupe key, default = kind
    image_url: str | None = None               # optional — push + Telegram photo
    deep_link: str | None = None               # frontend route the notification should open
    speak_text: str | None = None              # optional — text to TTS via Piper on HomePage WS
    severity: str = "info"                     # "info" | "warn" | "alert" — UI styling hint
    target_user_ids: list[int] | None = None   # None = broadcast to all admins
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_tag(self) -> str:
        return self.tag or self.kind


# ─── Channel toggles (admin settings) ──────────────────────────────────


async def _channel_enabled(session, channel: str) -> bool:
    """`channel` is one of telegram / push / ws_tts. Default True."""
    val = await _admin.get(session, f"notify_{channel}_enabled")
    return val is not False


# ─── Channel implementations ───────────────────────────────────────────


async def _send_telegram(notif: Notification) -> None:
    """Forward to the CARA Telegram bot owners. Uses the bot wrapper
    that's already initialised in `cara.integrations.telegram`."""
    from cara.integrations import telegram as _tg  # noqa: PLC0415

    text_lines = [f"*{notif.title}*"]
    if notif.body:
        text_lines.append(notif.body)
    if notif.deep_link:
        # cara.home.lan is the LAN-side hostname; the user's phone resolves
        # it via Pi-hole. From outside (Cloudflare Tunnel) the public domain
        # would substitute, configurable in admin_settings later.
        base = "https://cara.home.lan:8455"
        text_lines.append(f"\n→ {base}{notif.deep_link}")
    text = "\n".join(text_lines)

    try:
        await _tg.send_message_to_owners(
            text=text, parse_mode="Markdown", image_url=notif.image_url,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("notify.telegram.failed", kind=notif.kind, error=str(exc))


async def _send_push(notif: Notification) -> None:
    """Web Push VAPID — already wired to `push_subscriptions`."""
    from cara.services import push as _push  # noqa: PLC0415

    payload = {
        "title": notif.title,
        "body": notif.body,
        "tag": notif.effective_tag,
        "url": notif.deep_link or "/",
        "icon": notif.image_url,
    }
    try:
        await _push.broadcast_to_admins(payload, user_ids=notif.target_user_ids)
    except Exception as exc:  # noqa: BLE001
        log.warning("notify.push.failed", kind=notif.kind, error=str(exc))


async def _emit_ws_tts(notif: Notification) -> None:
    """Emit a `tts.play` event on the family bus. Subscribed HomePage
    tabs synthesise+play the audio. No-op when nothing's subscribed."""
    if not notif.speak_text:
        return
    from cara.services.family_bus import publish as _bus_publish  # noqa: PLC0415
    try:
        await _bus_publish(
            "tts.play",
            payload={
                "text": notif.speak_text,
                "kind": notif.kind,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("notify.ws_tts.failed", kind=notif.kind, error=str(exc))


# ─── Public entry point ───────────────────────────────────────────────


async def dispatch(notif: Notification) -> None:
    """Fan out the notification to every channel admin enabled. Each
    channel runs independently — one failure doesn't cancel the others.
    """
    from cara.store.db import get_sessionmaker  # noqa: PLC0415

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        tg = await _channel_enabled(s, "telegram")
        push = await _channel_enabled(s, "push")
        ws = await _channel_enabled(s, "ws_tts")

    coros = []
    if tg:
        coros.append(_send_telegram(notif))
    if push:
        coros.append(_send_push(notif))
    if ws and notif.speak_text:
        coros.append(_emit_ws_tts(notif))

    if not coros:
        return

    # gather with return_exceptions so a single channel crash doesn't
    # propagate and silence the others.
    results = await asyncio.gather(*coros, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            log.warning("notify.channel.exception", kind=notif.kind, error=repr(r))


def dispatch_nowait(notif: Notification) -> None:
    """Synchronous shim — schedule the dispatch on the running loop and
    return immediately. Use from inside async code: `dispatch_nowait(n)`
    won't block the chat orchestrator's event loop. Outside an async
    context (Celery task), prefer `await dispatch(...)`.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(dispatch(notif))
    except RuntimeError:
        asyncio.run(dispatch(notif))


# ─── Worker → backend handoff ─────────────────────────────────────────
#
# Celery workers can't hit the channels directly: the Telegram bot lives
# in the backend process, push subscriptions need the backend's DB
# engine, and WebSocket clients are connected to the backend uvicorn.
# Instead, workers PUBLISH a notification on a Redis pub/sub channel
# that the backend's lifespan subscriber consumes and turns into a
# real `dispatch()` call.

NOTIFY_BUS_KIND = "notify.request"


async def enqueue_for_backend(notif: Notification) -> None:
    """Publish a Notification on the family bus so the backend lifespan
    subscriber picks it up and runs `dispatch()` in-process. Safe to
    call from a Celery worker — only touches Redis, not the DB engine
    or any process-bound resources (bot / push clients / WS).
    """
    from cara.services.family_bus import publish as _bus_publish  # noqa: PLC0415

    payload = {
        "kind": notif.kind,
        "title": notif.title,
        "body": notif.body,
        "tag": notif.tag,
        "image_url": notif.image_url,
        "deep_link": notif.deep_link,
        "speak_text": notif.speak_text,
        "severity": notif.severity,
        "target_user_ids": notif.target_user_ids,
        "extra": notif.extra,
    }
    try:
        await _bus_publish(NOTIFY_BUS_KIND, payload=payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("notify.enqueue_failed", kind=notif.kind, error=str(exc))


def _from_payload(payload: dict[str, Any]) -> Notification:
    """Reconstruct a Notification from the bus payload."""
    return Notification(
        kind=str(payload.get("kind", "unknown")),
        title=str(payload.get("title", "")),
        body=str(payload.get("body", "")),
        tag=payload.get("tag"),
        image_url=payload.get("image_url"),
        deep_link=payload.get("deep_link"),
        speak_text=payload.get("speak_text"),
        severity=str(payload.get("severity", "info")),
        target_user_ids=payload.get("target_user_ids"),
        extra=payload.get("extra") or {},
    )


async def consume_dispatch_bus() -> None:
    """Long-running coroutine: subscribe to NOTIFY_BUS_KIND and dispatch
    each incoming notification. Started as a lifespan task in main.py.
    """
    from cara.services.family_bus import subscribe as _bus_subscribe  # noqa: PLC0415

    log.info("notify.bus_consumer.starting")
    try:
        async for event in _bus_subscribe():
            try:
                if event.get("kind") != NOTIFY_BUS_KIND:
                    continue
                payload = event.get("payload") or {}
                notif = _from_payload(payload)
                await dispatch(notif)
            except Exception as exc:  # noqa: BLE001
                log.warning("notify.bus_consumer.handler_failed", error=str(exc))
    except asyncio.CancelledError:
        log.info("notify.bus_consumer.cancelled")
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("notify.bus_consumer.crashed", error=str(exc))
