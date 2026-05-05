"""Calendar pull scheduler — runs as an asyncio task in the lifespan.

Per registered (user, scope_set='calendar:rw') credentials, every
`calendar_sync_interval_seconds` (default 300):

  1. List events using the stored sync_token (or the last-30-days window
     on the very first run).
  2. Upsert into `calendar_events` keyed on (provider, external_id).
  3. For events occurring in the next 7 days that aren't already linked
     to a task, create a task with `due_date=start_at` and link it back.
  4. Save the new sync_token in `oauth_credentials.config_json.sync_token`.

If the sync token is invalid (410 from Google), do a full sync.
Idempotent: running it twice produces no duplicates.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from cara.config import settings
from cara.integrations import google_calendar as gcal
from cara.integrations import google_oauth
from cara.models.calendar_event import CalendarEvent
from cara.models.oauth_credentials import OAuthCredentials


log = structlog.get_logger(__name__)


_BACKOFF_SECONDS = 30.0


async def _sync_one_user(
    sessionmaker: async_sessionmaker,
    cred_id: int,
) -> int:
    """Sync a single OAuth credentials row. Returns # events upserted."""
    async with sessionmaker() as session:
        cred = await session.get(OAuthCredentials, cred_id)
        if cred is None or cred.revoked:
            return 0
        if cred.scope_set != "calendar:rw":
            return 0

        cfg = cred.config_json or {}
        calendar_id = cfg.get("calendar_id") or "primary"
        sync_token = cfg.get("sync_token")

        try:
            access = await google_oauth.get_access_token(session, cred)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "calendar_sync.token_failed", cred_id=cred_id, error=str(exc),
            )
            return 0

    # Fetch outside the session so we don't hold a connection during HTTP.
    try:
        time_min = (
            datetime.now(timezone.utc) - timedelta(days=30)
            if not sync_token else None
        )
        events, next_sync = await gcal.list_events(
            access,
            calendar_id=calendar_id,
            sync_token=sync_token,
            time_min=time_min,
        )
        # 410 → next_sync is None and events is []; force full sync next loop.
        if not events and next_sync is None and sync_token:
            log.info("calendar_sync.token_expired", cred_id=cred_id)
            async with sessionmaker() as session:
                cred = await session.get(OAuthCredentials, cred_id)
                if cred is not None:
                    cred.config_json = {**(cred.config_json or {}), "sync_token": None}
                    await session.commit()
            return 0
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "calendar_sync.list_failed", cred_id=cred_id, error=str(exc),
        )
        return 0

    if not events:
        if next_sync:
            async with sessionmaker() as session:
                cred = await session.get(OAuthCredentials, cred_id)
                if cred is not None:
                    cred.config_json = {**(cred.config_json or {}), "sync_token": next_sync}
                    cred.last_synced_at = datetime.now(timezone.utc)
                    await session.commit()
        return 0

    upserted = 0
    async with sessionmaker() as session:
        cred = await session.get(OAuthCredentials, cred_id)
        if cred is None:
            return 0
        for ev in events:
            try:
                upserted += await _upsert_event(session, cred.user_id, calendar_id, ev)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "calendar_sync.upsert_failed",
                    event_id=ev.get("id"), error=str(exc),
                )
        if next_sync:
            cred.config_json = {**(cred.config_json or {}), "sync_token": next_sync, "calendar_id": calendar_id}
        cred.last_synced_at = datetime.now(timezone.utc)
        await session.commit()
    return upserted


async def _upsert_event(
    session,  # AsyncSession
    user_id: int,
    calendar_id: str,
    ev: dict[str, Any],
) -> int:
    """Upsert one Google event into calendar_events + maybe link a task."""
    external_id = ev.get("id")
    if not external_id:
        return 0

    # Skip events that WE created (avoid double-import loop).
    if gcal.is_cara_managed(ev):
        return 0

    status = ev.get("status")
    title = ev.get("summary") or "(senza titolo)"
    desc = ev.get("description")
    location = ev.get("location")
    etag = (ev.get("etag") or "").strip('"')
    rrule = None
    if ev.get("recurrence"):
        rrule = "\n".join(ev["recurrence"])
    start_dt, all_day = gcal.parse_event_dt(ev.get("start"))
    end_dt, _ = gcal.parse_event_dt(ev.get("end"))
    attendees = {"items": ev.get("attendees", [])}

    existing = (
        await session.execute(
            select(CalendarEvent)
            .where(CalendarEvent.provider == "google")
            .where(CalendarEvent.external_id == external_id)
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is not None:
        if status == "cancelled":
            # Drop the linked task as well.
            if existing.linked_task_id is not None:
                try:
                    from cara.services import tasks as task_svc
                    await task_svc.delete_task(
                        session, existing.linked_task_id,
                        user_id=user_id,
                    )
                except Exception:  # noqa: BLE001
                    pass
            await session.delete(existing)
            return 1
        existing.title = title
        existing.description = desc
        existing.location = location
        existing.start_at = start_dt
        existing.end_at = end_dt
        existing.all_day = all_day
        existing.recurrence_rule = rrule
        existing.attendees = attendees
        existing.status = status
        existing.etag = etag
        existing.last_pulled_at = now
        # Keep the linked task title in sync if we created one.
        if existing.linked_task_id is not None and start_dt is not None:
            try:
                from cara.services import tasks as task_svc
                await task_svc.update_task(
                    session, existing.linked_task_id,
                    user_id=user_id,
                    title=title,
                    due_date=start_dt,
                )
            except Exception:  # noqa: BLE001
                pass
        return 1

    # New event — link a task if it occurs within the next 7 days.
    cev = CalendarEvent(
        user_id=user_id,
        provider="google",
        external_id=external_id,
        calendar_id=calendar_id,
        title=title,
        description=desc,
        start_at=start_dt,
        end_at=end_dt,
        location=location,
        recurrence_rule=rrule,
        all_day=all_day,
        attendees=attendees,
        status=status,
        etag=etag,
        last_pulled_at=now,
    )
    if (
        status != "cancelled"
        and start_dt is not None
        and start_dt <= now + timedelta(days=7)
        and start_dt >= now - timedelta(hours=12)
    ):
        try:
            from cara.services import tasks as task_svc
            t = await task_svc.create_task(
                session, user_id=user_id, title=title, due_date=start_dt,
            )
            cev.linked_task_id = t.id
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "calendar_sync.task_link_failed",
                event=external_id, error=str(exc),
            )

    session.add(cev)
    return 1


async def _scan_once(sessionmaker: async_sessionmaker) -> int:
    """One sweep across all active calendar credentials."""
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(OAuthCredentials.id)
                .where(OAuthCredentials.provider == "google")
                .where(OAuthCredentials.scope_set == "calendar:rw")
                .where(OAuthCredentials.revoked.is_(False))
            )
        ).all()
        cred_ids = [r[0] for r in rows]

    total = 0
    for cid in cred_ids:
        try:
            total += await _sync_one_user(sessionmaker, cid)
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar_sync.user_failed", cred_id=cid, error=str(exc))
    return total


async def run_loop(sessionmaker: async_sessionmaker) -> None:
    if not google_oauth.is_available():
        log.info("calendar_sync.skipped_unconfigured")
        return
    interval = max(60, settings.calendar_sync_interval_seconds)
    log.info("calendar_sync.start", interval_seconds=interval)
    try:
        while True:
            try:
                n = await _scan_once(sessionmaker)
                if n:
                    log.info("calendar_sync.tick", events=n)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("calendar_sync.tick_error", error=str(exc))
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("calendar_sync.stop")
        raise
