"""Mail agent — Celery tasks for Gmail scanning and Calendar two-way
sync. Replaces the asyncio loops that used to live in `cara.main`'s
lifespan.

Both tasks reuse the existing service modules under
`cara.services.integrations.*` for the actual logic — the Celery
wrapper here only owns scheduling, queue routing, and idempotency.
That way moving from asyncio loop to agent worker doesn't change
behaviour: same scans, same upsert rules, same proposals.

Tasks are SAFE to run concurrently with the FastAPI process and with
each other — they only read OAuth credentials + write to
`email_proposals` / `calendar_events` / `tasks`, none of which the
chat path mutates synchronously.
"""

from __future__ import annotations

from typing import Any

import structlog

from cara.agents._base import _get_sessionmaker, cara_task
from cara.integrations import google_oauth
from cara.services.integrations.calendar_sync import _scan_once as calendar_scan_once
from cara.services.integrations.gmail_scanner import _scan_once as gmail_scan_once


log = structlog.get_logger(__name__)


@cara_task(agent="mail")
async def scan_gmail(idempotency_key: str | None = None) -> dict[str, Any]:
    """Scan every connected user's Gmail for proposal candidates.

    Idempotent at the message level (`gmail_scanner` already dedups by
    `message_id` via the EmailProposal UNIQUE constraint), so this
    task itself does NOT take an idempotency key — it always runs and
    just writes nothing if no new mail arrived.
    """
    if not google_oauth.is_available():
        log.info("agent.mail.scan_gmail.skipped_no_oauth")
        return {"skipped": "google_oauth_not_configured", "scanned": 0}
    sessionmaker = _get_sessionmaker()
    n = await gmail_scan_once(sessionmaker)
    log.info("agent.mail.scan_gmail.done", users_scanned=n)
    return {"users_scanned": n}


@cara_task(agent="mail")
async def sync_calendar(idempotency_key: str | None = None) -> dict[str, Any]:
    """Pull Google Calendar events for every connected user, upsert
    into `calendar_events`, and link to tasks for events within 7 days.
    """
    if not google_oauth.is_available():
        log.info("agent.mail.sync_calendar.skipped_no_oauth")
        return {"skipped": "google_oauth_not_configured", "synced": 0}
    sessionmaker = _get_sessionmaker()
    n = await calendar_scan_once(sessionmaker)
    log.info("agent.mail.sync_calendar.done", users_synced=n)
    return {"users_synced": n}
