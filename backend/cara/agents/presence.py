"""Presence agent — polls frigate-faces for arrivals, debounces via
cooldown, persists `PresenceEvent` rows, and dispatches notifications
to Telegram + Web Push + WebSocket TTS through `cara.services.notify`.

Beat schedule: every 30 s. The poll itself is cheap (one HTTP call to
frigate-faces returning <50 KB), so 30 s gives a usable arrival
latency without hammering anything.

Cooldown logic:
- Known person: max 1 greeting per `presence_greeting_cooldown_min_known`
  (default 30 min) per person — uses Redis key `presence:greet:<name>`
- Unknown: max 1 alert per `presence_greeting_cooldown_min_unknown`
  (default 5 min) per camera — uses Redis key
  `presence:unknown:<camera>`

Silent hours (default 22-08 Europe/Rome): voice greeting is suppressed,
push + Telegram still fire so the admin knows.

Idempotency: each frigate-faces sighting has a globally-unique id;
PresenceEvent.sighting_id has a UNIQUE constraint, so a re-run can't
duplicate. The agent watermark `presence:last_sighting_id` tracks the
highest id we've already processed.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

import httpx
import structlog

from cara.agents._base import _get_sessionmaker, cara_task


log = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(4.0, connect=2.0)


@cara_task(agent="presence")
async def poll_arrivals(idempotency_key: str | None = None) -> dict[str, Any]:
    """Pull recent sightings from frigate-faces, fan out notifications
    for the new ones (debounced by cooldown). Idempotent across runs
    via the sighting_id UNIQUE constraint."""
    from cara.services import admin_settings as _admin  # noqa: PLC0415
    from cara.config import settings  # noqa: PLC0415

    sessionmaker = _get_sessionmaker()

    # Read settings + watermark.
    async with sessionmaker() as s:
        ff_url = (
            await _admin.get(s, "frigate_faces_url")
            or settings.frigate_faces_url
            or ""
        ).rstrip("/")
        cooldown_known = int(
            await _admin.get(s, "presence_greeting_cooldown_min_known") or 30
        )
        cooldown_unknown = int(
            await _admin.get(s, "presence_greeting_cooldown_min_unknown") or 5
        )
        silent_raw = await _admin.get(s, "presence_greeting_silent_hours")
        greeting_enabled = (
            await _admin.get(s, "presence_greeting_enabled")
        ) is not False

    if not ff_url:
        return {"skipped": "frigate_faces_not_configured", "new": 0}

    # Parse silent hours.
    silent_start, silent_end = _parse_silent(silent_raw)

    # frigate-faces doesn't expose a /api/sightings list, so we
    # detect arrivals via two sources:
    #   - /api/people    → known people. Arrival = last_seen advanced.
    #   - /api/unknown   → unknown sightings (latest at top).
    # Each source has its own watermark in Redis.
    redis_client = await _redis()
    new_count = 0
    skipped_cooldown = 0
    now = datetime.now(timezone.utc)
    in_silent = _in_silent_window(now, silent_start, silent_end)

    # ─── Known people: arrival detection by last_seen advance ─────
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
            r = await c.get(f"{ff_url}/api/people")
            r.raise_for_status()
            people = r.json() or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("presence.fetch_people_failed", error=str(exc))
        people = []

    for p in people:
        try:
            person_id = int(p.get("id") or 0)
            person_name = _normalise_name(str(p.get("name") or ""))
            last_seen_iso = p.get("last_seen") or ""
            if not person_id or not person_name or not last_seen_iso:
                continue
        except (TypeError, ValueError):
            continue

        last_seen_dt = _parse_iso(last_seen_iso)
        if last_seen_dt is None:
            continue
        last_seen_unix = int(last_seen_dt.timestamp())

        watermark_key = f"presence:wm:person:{person_id}"
        prev_unix = 0
        if redis_client:
            try:
                prev_unix = int(await redis_client.get(watermark_key) or 0)
            except Exception:  # noqa: BLE001
                prev_unix = 0

        if last_seen_unix <= prev_unix:
            # No new arrival since last poll.
            continue

        # Cooldown — same person, multiple cameras within 30 min → 1 greeting.
        cooldown_key = f"presence:greet:{person_name.lower()}"
        if redis_client and await _cooldown_active(redis_client, cooldown_key):
            skipped_cooldown += 1
            if redis_client:
                try:
                    await redis_client.set(watermark_key, str(last_seen_unix))
                except Exception:  # noqa: BLE001
                    pass
            continue

        camera_id = "unknown"  # /api/people doesn't expose the camera
        snapshot_url = None
        latest_image = p.get("latest_image")
        if latest_image:
            snapshot_url = f"{ff_url}/api/image/{latest_image}"

        # Fake a sighting_id from last_seen unix so the UNIQUE
        # constraint dedupes a re-run of the same arrival.
        synthetic_sighting_id = person_id * 10_000_000 + last_seen_unix

        async with sessionmaker() as session:
            from cara.models.presence_event import PresenceEvent  # noqa: PLC0415

            evt = PresenceEvent(
                sighting_id=synthetic_sighting_id,
                person_id=person_id,
                person_name=person_name,
                camera_id=camera_id,
                is_known=True,
                seen_at=last_seen_dt,
                snapshot_url=snapshot_url,
                extra={"source": "people_poll", "latest_image": latest_image},
            )
            session.add(evt)
            try:
                await session.flush()
                await session.commit()
                evt_id = evt.id
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                log.debug("presence.duplicate_skipped", sighting_id=synthetic_sighting_id, error=str(exc))
                if redis_client:
                    try:
                        await redis_client.set(watermark_key, str(last_seen_unix))
                    except Exception:  # noqa: BLE001
                        pass
                continue

        if greeting_enabled and bool(p.get("notify", 1)):
            await _dispatch_arrival(
                evt_id=evt_id,
                person_name=person_name,
                is_known=True,
                camera_id=camera_id,
                snapshot_url=snapshot_url,
                in_silent=in_silent,
            )

        if redis_client:
            try:
                await redis_client.set(watermark_key, str(last_seen_unix))
                await _cooldown_set(redis_client, cooldown_key, cooldown_known * 60)
            except Exception:  # noqa: BLE001
                pass

        new_count += 1

    # ─── Unknown sightings ────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
            r = await c.get(f"{ff_url}/api/unknown")
            r.raise_for_status()
            unknowns = r.json() or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("presence.fetch_unknown_failed", error=str(exc))
        unknowns = []

    # Latest unknown sighting id we've already processed.
    last_unk_id = 0
    if redis_client:
        try:
            last_unk_id = int(await redis_client.get("presence:wm:unknown") or 0)
        except Exception:  # noqa: BLE001
            last_unk_id = 0

    for u in sorted(unknowns, key=lambda x: int(x.get("id") or 0)):
        try:
            sid = int(u.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if sid <= last_unk_id:
            continue

        camera_id = str(u.get("camera") or "unknown")
        seen_at_iso = u.get("timestamp") or u.get("created_at")
        seen_dt = _parse_iso(seen_at_iso) or now
        cooldown_key = f"presence:unknown:{camera_id}"

        if redis_client and await _cooldown_active(redis_client, cooldown_key):
            skipped_cooldown += 1
            if redis_client:
                try:
                    await redis_client.set("presence:wm:unknown", str(sid))
                except Exception:  # noqa: BLE001
                    pass
            continue

        snapshot_url = None
        img = u.get("image") or u.get("filename")
        if img:
            snapshot_url = f"{ff_url}/api/image/{img}"

        async with sessionmaker() as session:
            from cara.models.presence_event import PresenceEvent  # noqa: PLC0415

            evt = PresenceEvent(
                sighting_id=sid,
                person_id=None,
                person_name="Sconosciuto",
                camera_id=camera_id,
                is_known=False,
                seen_at=seen_dt,
                snapshot_url=snapshot_url,
                extra={"source": "unknown_poll", "raw": u},
            )
            session.add(evt)
            try:
                await session.flush()
                await session.commit()
                evt_id = evt.id
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                log.debug("presence.unknown_duplicate", sid=sid, error=str(exc))
                if redis_client:
                    try:
                        await redis_client.set("presence:wm:unknown", str(sid))
                    except Exception:  # noqa: BLE001
                        pass
                continue

        if greeting_enabled:
            await _dispatch_arrival(
                evt_id=evt_id,
                person_name="Sconosciuto",
                is_known=False,
                camera_id=camera_id,
                snapshot_url=snapshot_url,
                in_silent=in_silent,
            )

        if redis_client:
            try:
                await redis_client.set("presence:wm:unknown", str(sid))
                await _cooldown_set(redis_client, cooldown_key, cooldown_unknown * 60)
            except Exception:  # noqa: BLE001
                pass

        new_count += 1

    return {
        "new": new_count,
        "skipped_cooldown": skipped_cooldown,
        "people_checked": len(people),
        "unknown_checked": len(unknowns),
    }


# ─── Helpers ───────────────────────────────────────────────────────────


def _normalise_name(name: str) -> str:
    """frigate-faces is case-sensitive (`Ilaria` vs `ilaria`); we
    title-case for display so duplicates collapse."""
    return name.strip().title()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def _parse_silent(raw: Any) -> tuple[time | None, time | None]:
    """Accept `[22, 8]` (hour ints) or `["22:00", "08:00"]`. Returns
    (None, None) when the setting is missing or invalid."""
    if not raw or not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None, None
    try:
        out = []
        for v in raw:
            if isinstance(v, int):
                out.append(time(hour=int(v) % 24))
            elif isinstance(v, str):
                hh, _, mm = v.partition(":")
                out.append(time(hour=int(hh) % 24, minute=int(mm or 0) % 60))
            else:
                return None, None
        return out[0], out[1]
    except (ValueError, TypeError):
        return None, None


def _in_silent_window(
    now: datetime, start: time | None, end: time | None
) -> bool:
    if start is None or end is None:
        return False
    # Convert to Europe/Rome wall clock since the user thinks in
    # local hours (configured in admin_settings as 22-08 = night).
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        local = now.astimezone(ZoneInfo("Europe/Rome")).time()
    except Exception:  # noqa: BLE001
        local = now.time()
    if start <= end:
        return start <= local < end
    # Overnight wrap: 22:00 → 08:00 next day.
    return local >= start or local < end


async def _redis():
    """Lazy Redis connection — same DB as the rest of CARA. Returns
    None when Redis is unreachable; the agent degrades gracefully."""
    try:
        from redis.asyncio import Redis  # noqa: PLC0415
        from cara.config import settings  # noqa: PLC0415

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        # Ping to surface auth/network errors early.
        await client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        log.warning("presence.redis_unavailable", error=str(exc))
        return None


async def _watermark_get(redis_client) -> int:
    if not redis_client:
        return 0
    try:
        v = await redis_client.get("presence:last_sighting_id")
        return int(v or 0)
    except Exception:  # noqa: BLE001
        return 0


async def _watermark_set(redis_client, sighting_id: int) -> None:
    if not redis_client:
        return
    try:
        cur = await _watermark_get(redis_client)
        if sighting_id > cur:
            await redis_client.set("presence:last_sighting_id", str(sighting_id))
    except Exception:  # noqa: BLE001
        return


async def _cooldown_active(redis_client, key: str) -> bool:
    if not redis_client:
        return False
    try:
        return bool(await redis_client.exists(key))
    except Exception:  # noqa: BLE001
        return False


async def _cooldown_set(redis_client, key: str, ttl_seconds: int) -> None:
    if not redis_client:
        return
    try:
        await redis_client.setex(key, ttl_seconds, "1")
    except Exception:  # noqa: BLE001
        return


async def _dispatch_arrival(
    *,
    evt_id: int,
    person_name: str,
    is_known: bool,
    camera_id: str,
    snapshot_url: str | None,
    in_silent: bool,
) -> None:
    """Build a Notification and hand it to the dispatcher. Voice-only
    text is suppressed during silent hours; push + Telegram still fire."""
    from cara.services.notify import Notification, enqueue_for_backend  # noqa: PLC0415

    if is_known:
        title = f"🚪 {person_name} è arrivato"
        body = f"avvistato su {camera_id}"
        speak = None if in_silent else f"Ciao {person_name}, bentornato!"
        deep_link = "/wallet"
    else:
        title = "🚪 Sconosciuto in casa"
        body = f"volto non riconosciuto su {camera_id}"
        speak = None if in_silent else "Ciao, chi sei? Fatti riconoscere."
        deep_link = "/admin/persone"

    notif = Notification(
        kind="presence.arrival" if is_known else "presence.unknown",
        title=title,
        body=body,
        tag=f"presence:{person_name}:{camera_id}",
        image_url=snapshot_url,
        deep_link=deep_link,
        speak_text=speak,
        severity="info" if is_known else "warn",
        extra={"event_id": evt_id, "camera_id": camera_id},
    )
    try:
        await enqueue_for_backend(notif)
    except Exception as exc:  # noqa: BLE001
        log.warning("presence.dispatch_failed", evt_id=evt_id, error=str(exc))
