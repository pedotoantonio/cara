"""Push hook: when a task is created/updated/deleted in Cara AND the
user has the calendar push direction enabled, publish to their Google
Calendar.

Fire-and-forget (asyncio task). Failures are logged, don't block the
HTTP request that triggered them.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cara.integrations import google_calendar as gcal
from cara.integrations import google_oauth
from cara.models.oauth_credentials import OAuthCredentials
from cara.models.task import Task


log = structlog.get_logger(__name__)


async def _get_push_creds(
    session: AsyncSession, user_id: int,
) -> tuple[OAuthCredentials, str] | None:
    """Return (cred, calendar_id) when the user has push enabled, else None."""
    cred = (
        await session.execute(
            select(OAuthCredentials)
            .where(OAuthCredentials.user_id == user_id)
            .where(OAuthCredentials.provider == "google")
            .where(OAuthCredentials.scope_set == "calendar:rw")
            .where(OAuthCredentials.revoked.is_(False))
        )
    ).scalar_one_or_none()
    if cred is None:
        return None
    cfg = cred.config_json or {}
    if not cfg.get("push_enabled"):
        return None
    return cred, cfg.get("calendar_id") or "primary"


async def _maybe_push_create(sessionmaker: async_sessionmaker, task_id, user_id: int) -> None:
    async with sessionmaker() as session:
        bundle = await _get_push_creds(session, user_id)
        if bundle is None:
            return
        cred, calendar_id = bundle
        task = await session.get(Task, task_id)
        if task is None or task.due_date is None:
            return
        try:
            token = await google_oauth.get_access_token(session, cred)
            event = await gcal.insert_event(
                token,
                calendar_id=calendar_id,
                title=task.title,
                due_at=task.due_date,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar_push.create_failed", task_id=str(task_id), error=str(exc))
            return
        task.calendar_external_id = event.get("id")
        await session.commit()
        log.info("calendar_push.created", task_id=str(task_id), event_id=event.get("id"))


async def _maybe_push_update(sessionmaker: async_sessionmaker, task_id, user_id: int) -> None:
    async with sessionmaker() as session:
        bundle = await _get_push_creds(session, user_id)
        if bundle is None:
            return
        cred, calendar_id = bundle
        task = await session.get(Task, task_id)
        if task is None:
            return
        if not task.calendar_external_id:
            # Was created locally before push was enabled — promote.
            if task.due_date is not None:
                try:
                    token = await google_oauth.get_access_token(session, cred)
                    event = await gcal.insert_event(
                        token,
                        calendar_id=calendar_id,
                        title=task.title,
                        due_at=task.due_date,
                    )
                    task.calendar_external_id = event.get("id")
                    await session.commit()
                except Exception as exc:  # noqa: BLE001
                    log.warning("calendar_push.create_on_update_failed", error=str(exc))
            return
        try:
            token = await google_oauth.get_access_token(session, cred)
            await gcal.patch_event(
                token,
                calendar_id=calendar_id,
                event_id=task.calendar_external_id,
                title=task.title,
                due_at=task.due_date,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar_push.patch_failed", task_id=str(task_id), error=str(exc))


async def _maybe_push_delete(
    sessionmaker: async_sessionmaker,
    *,
    user_id: int,
    external_id: str,
) -> None:
    async with sessionmaker() as session:
        bundle = await _get_push_creds(session, user_id)
        if bundle is None:
            return
        cred, calendar_id = bundle
        try:
            token = await google_oauth.get_access_token(session, cred)
            await gcal.delete_event(
                token, calendar_id=calendar_id, event_id=external_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar_push.delete_failed", external_id=external_id, error=str(exc))


def schedule_create(sessionmaker, task_id, user_id: int) -> None:
    """Fire-and-forget. Returns immediately."""
    asyncio.create_task(_maybe_push_create(sessionmaker, task_id, user_id))


def schedule_update(sessionmaker, task_id, user_id: int) -> None:
    asyncio.create_task(_maybe_push_update(sessionmaker, task_id, user_id))


def schedule_delete(sessionmaker, *, user_id: int, external_id: str) -> None:
    asyncio.create_task(_maybe_push_delete(sessionmaker, user_id=user_id, external_id=external_id))


# `Any` is referenced in the dict-like signatures above; no bare alias needed.
_unused: Any | None = None

