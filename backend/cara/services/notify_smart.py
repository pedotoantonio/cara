"""Smart notification policy: bundling + DND + priority.

Wraps `cara.services.notify.dispatch()` con tre policy:

1. **DND (Do Not Disturb)**: quiet_hours_start / quiet_hours_end
   admin setting. Notifiche non-urgent durante l'intervallo vengono
   accodate in Redis, fan-out al risveglio.
2. **Bundling**: notifiche dello stesso `kind` per lo stesso `user_id`
   entro una finestra di N secondi (default 300 = 5 min) vengono
   accumulate e fan-out come singola notifica summary.
3. **Priority bypass**: `urgent=True` bypassa SEMPRE DND e bundling.

Compatibile back-compat: il vecchio `notify.dispatch()` è chiamato
direttamente da molti punti del codice. Per attivare smart policy,
i callsite devono usare `notify_smart.dispatch_smart()`. Migration
graduale.

Setting admin in `admin_settings` (chiavi nuove):
- `notify_quiet_hours_enabled`: bool, default true
- `notify_quiet_hours_start`: str "22:00"
- `notify_quiet_hours_end`: str "07:00"
- `notify_bundle_window_seconds`: int, default 300
- `notify_bundle_max_items`: int, default 5 (oltre questo, fan-out)

Setting per-user override in futuro: `users.quiet_hours_*` (M2).
"""

from __future__ import annotations

import json
from datetime import datetime, time as dtime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from redis.asyncio import Redis

from cara.config import settings
from cara.services import admin_settings as _admin
from cara.services import notify as _notify
from cara.services.notify import Notification


log = structlog.get_logger(__name__)


_BUNDLE_KEY_PREFIX = "notify:bundle"
_DND_QUEUE_KEY = "notify:dnd_queue"
_ROME = ZoneInfo("Europe/Rome")


async def _get_redis() -> Redis:
    """Connessione Redis condivisa (riusa quella del notify esistente
    se esposta, altrimenti apre lock locale)."""
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _is_in_quiet_hours(now: datetime, start_str: str, end_str: str) -> bool:
    """True se `now` (timezone-aware) cade nel quiet-hours range.

    Gestisce overnight-wrap: se end < start (es. 22:00→07:00) il range
    è "from start to end of day OR from start-of-day to end".
    """
    local = now.astimezone(_ROME)
    try:
        sh, sm = (int(x) for x in start_str.split(":"))
        eh, em = (int(x) for x in end_str.split(":"))
    except (ValueError, AttributeError):
        return False
    start = dtime(sh, sm)
    end = dtime(eh, em)
    cur = local.time()
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    # overnight wrap (22:00 → 07:00)
    return cur >= start or cur < end


async def _read_settings(session: Any) -> dict[str, Any]:
    s = await _admin.get_all(session)
    return {
        "dnd_enabled": bool(s.get("notify_quiet_hours_enabled", True)),
        "dnd_start": str(s.get("notify_quiet_hours_start", "22:00")),
        "dnd_end": str(s.get("notify_quiet_hours_end", "07:00")),
        "bundle_window": int(s.get("notify_bundle_window_seconds", 300)),
        "bundle_max": int(s.get("notify_bundle_max_items", 5)),
    }


async def dispatch_smart(
    notification: Notification,
    session: Any,
    *,
    bundle_key_extra: str | None = None,
) -> str:
    """Applica policy DND + bundling + priority, poi fan-out.

    Returns: una delle stringhe
        - "dispatched"     → notifica consegnata subito
        - "bundled"        → accumulata in finestra, fan-out summary alla
                              scadenza (gestito da bundle_flusher worker)
        - "queued_dnd"     → posticipata a fine quiet hours
        - "dropped"        → policy rifiuta (es. duplicato esatto entro 60s)
    """
    is_urgent = bool(getattr(notification, "urgent", False))
    user_id = notification.user_id
    kind = notification.kind

    # Urgenti SEMPRE consegnate. Fan-out immediato.
    if is_urgent:
        await _notify.dispatch(notification)
        log.info("notify.smart.urgent_bypass", kind=kind, user_id=user_id)
        return "dispatched"

    cfg = await _read_settings(session)
    now = datetime.now(timezone.utc)

    # DND check
    if cfg["dnd_enabled"] and _is_in_quiet_hours(
        now, cfg["dnd_start"], cfg["dnd_end"]
    ):
        await _queue_dnd(notification)
        log.info(
            "notify.smart.dnd_queued",
            kind=kind,
            user_id=user_id,
            until=cfg["dnd_end"],
        )
        return "queued_dnd"

    # Bundling check: scrivi in finestra Redis, non fan-out direct
    bundle_id = f"{user_id}:{kind}"
    if bundle_key_extra:
        bundle_id += f":{bundle_key_extra}"
    bundled = await _add_to_bundle(
        bundle_id, notification, cfg["bundle_window"], cfg["bundle_max"]
    )
    if bundled == "deferred":
        log.info("notify.smart.bundled", bundle_id=bundle_id)
        return "bundled"
    if bundled == "burst_threshold_reached":
        # Troppi nella finestra → fan-out subito come summary
        items = await _drain_bundle(bundle_id)
        summary = _build_summary(items)
        await _notify.dispatch(summary)
        return "dispatched"

    # Default fallback: dispatch immediato (primo della finestra)
    await _notify.dispatch(notification)
    return "dispatched"


async def _queue_dnd(notification: Notification) -> None:
    redis = await _get_redis()
    try:
        payload = json.dumps(
            {
                "kind": notification.kind,
                "user_id": notification.user_id,
                "title": notification.title,
                "body": notification.body,
                "data": getattr(notification, "data", {}),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        await redis.rpush(_DND_QUEUE_KEY, payload)
    finally:
        await redis.aclose()


async def _add_to_bundle(
    bundle_id: str,
    notification: Notification,
    window_sec: int,
    max_items: int,
) -> str:
    """Push in bundle list + set TTL. Returns:
    - 'first' se primo della finestra (caller fan-out subito)
    - 'deferred' se aggiunto a bundle esistente
    - 'burst_threshold_reached' se ha superato max_items
    """
    redis = await _get_redis()
    try:
        key = f"{_BUNDLE_KEY_PREFIX}:{bundle_id}"
        payload = json.dumps(
            {
                "title": notification.title,
                "body": notification.body,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        pipe = redis.pipeline()
        pipe.rpush(key, payload)
        pipe.expire(key, window_sec)
        pipe.llen(key)
        _, _, length = await pipe.execute()
        if length == 1:
            return "first"
        if length >= max_items:
            return "burst_threshold_reached"
        return "deferred"
    finally:
        await redis.aclose()


async def _drain_bundle(bundle_id: str) -> list[dict[str, Any]]:
    redis = await _get_redis()
    try:
        key = f"{_BUNDLE_KEY_PREFIX}:{bundle_id}"
        raw_items = await redis.lrange(key, 0, -1)
        await redis.delete(key)
        return [json.loads(x) for x in raw_items]
    finally:
        await redis.aclose()


def _build_summary(items: list[dict[str, Any]]) -> Notification:
    """Costruisce una Notification summary da N item bundlati.

    Heuristic: titolo "N novità da CARA", body è la concatenazione
    dei primi 3 titoli + "... e altri N-3".
    """
    n = len(items)
    titles = [it.get("title", "") for it in items]
    head = ", ".join(titles[:3])
    body = head if n <= 3 else f"{head} … e altri {n - 3}"
    # Crea Notification minimale — il chiamante non passa il context
    # completo; per ora i bundled sono notify-only (no actions).
    return Notification(
        kind="bundle_summary",
        user_id=items[0].get("user_id") if items else None,
        title=f"{n} novità da CARA",
        body=body,
    )
