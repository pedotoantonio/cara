"""Thin async wrapper around Google Calendar v3 REST.

We don't use `google-api-python-client` (which is sync only) — instead
we hit the REST endpoints directly with httpx.AsyncClient. This avoids
running blocking IO inside the asyncio event loop.

Two methods used by the scheduler:

  - list_calendars(token)
  - list_events(token, calendar_id, sync_token | time_min)
  - insert_event / patch_event / delete_event (Phase B)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog


log = structlog.get_logger(__name__)


_API_BASE = "https://www.googleapis.com/calendar/v3"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def list_calendars(token: str) -> list[dict[str, Any]]:
    """Return [{id, summary, primary}] for all calendars the user has."""
    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.get(
            f"{_API_BASE}/users/me/calendarList",
            headers=_headers(token),
        )
        resp.raise_for_status()
    items = resp.json().get("items", [])
    return [
        {
            "id": x.get("id"),
            "summary": x.get("summary"),
            "primary": bool(x.get("primary")),
            "access_role": x.get("accessRole"),
        }
        for x in items
    ]


async def list_events(
    token: str,
    *,
    calendar_id: str,
    sync_token: str | None = None,
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    page_size: int = 100,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return (events, next_sync_token).

    First call: pass `time_min=...` (e.g. now-7days). Successive calls:
    pass the `next_sync_token` we returned previously to get only the
    delta.
    """
    params: dict[str, Any] = {
        "maxResults": page_size,
        "singleEvents": "true",
        "showDeleted": "true",
    }
    if sync_token:
        params["syncToken"] = sync_token
    else:
        if time_min is not None:
            params["timeMin"] = time_min.isoformat().replace("+00:00", "Z")
        if time_max is not None:
            params["timeMax"] = time_max.isoformat().replace("+00:00", "Z")

    all_items: list[dict[str, Any]] = []
    page_token: str | None = None
    next_sync: str | None = None

    async with httpx.AsyncClient(timeout=20.0) as c:
        while True:
            if page_token:
                params["pageToken"] = page_token
            resp = await c.get(
                f"{_API_BASE}/calendars/{calendar_id}/events",
                headers=_headers(token),
                params=params,
            )
            if resp.status_code == 410:
                # syncToken expired — caller must do a full sync.
                return [], None
            resp.raise_for_status()
            body = resp.json()
            all_items.extend(body.get("items", []))
            page_token = body.get("nextPageToken")
            next_sync = body.get("nextSyncToken")
            if not page_token:
                break

    return all_items, next_sync


def parse_event_dt(raw: dict[str, Any] | None) -> tuple[datetime | None, bool]:
    """Convert a Google `start`/`end` block into (datetime, all_day)."""
    if not raw:
        return None, False
    if "dateTime" in raw:
        s = raw["dateTime"]
        # Google returns "2026-05-12T09:30:00+02:00" — fromisoformat handles it.
        return datetime.fromisoformat(s), False
    if "date" in raw:
        # All-day event — interpret as midnight UTC.
        d = raw["date"]
        return datetime.fromisoformat(d).replace(tzinfo=timezone.utc), True
    return None, False


# ---------------------------------------------------------------------------
# Phase B — write back
# ---------------------------------------------------------------------------


CARA_MARKER_PROP = "cara_managed"   # extendedProperties.private flag


def _to_event_payload(
    *, title: str, due_at: datetime, duration_minutes: int = 30,
    description: str | None = None,
) -> dict[str, Any]:
    end = due_at.replace(microsecond=0)
    end_with = end + (end - end)  # placeholder to silence type checker
    _ = end_with                  # noqa: F841
    from datetime import timedelta as _td
    finish = due_at + _td(minutes=duration_minutes)
    return {
        "summary": title,
        "description": description or "",
        "start": {"dateTime": due_at.isoformat()},
        "end": {"dateTime": finish.isoformat()},
        "extendedProperties": {
            "private": {CARA_MARKER_PROP: "1"},
        },
    }


async def insert_event(
    token: str,
    *,
    calendar_id: str,
    title: str,
    due_at: datetime,
    description: str | None = None,
    duration_minutes: int = 30,
) -> dict[str, Any]:
    body = _to_event_payload(
        title=title, due_at=due_at,
        duration_minutes=duration_minutes,
        description=description,
    )
    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.post(
            f"{_API_BASE}/calendars/{calendar_id}/events",
            headers={**_headers(token), "Content-Type": "application/json"},
            json=body,
        )
        resp.raise_for_status()
    return resp.json()


async def patch_event(
    token: str,
    *,
    calendar_id: str,
    event_id: str,
    title: str | None = None,
    due_at: datetime | None = None,
    description: str | None = None,
    duration_minutes: int = 30,
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if title is not None:
        patch["summary"] = title
    if description is not None:
        patch["description"] = description
    if due_at is not None:
        from datetime import timedelta as _td
        finish = due_at + _td(minutes=duration_minutes)
        patch["start"] = {"dateTime": due_at.isoformat()}
        patch["end"] = {"dateTime": finish.isoformat()}

    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.patch(
            f"{_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers={**_headers(token), "Content-Type": "application/json"},
            json=patch,
        )
        resp.raise_for_status()
    return resp.json()


async def delete_event(
    token: str,
    *,
    calendar_id: str,
    event_id: str,
) -> bool:
    async with httpx.AsyncClient(timeout=10.0) as c:
        resp = await c.delete(
            f"{_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers=_headers(token),
        )
    return resp.status_code in (200, 204, 404)


def is_cara_managed(event: dict[str, Any]) -> bool:
    """True if the event was created BY Cara (so we skip re-importing)."""
    ext = (event.get("extendedProperties") or {}).get("private") or {}
    return str(ext.get(CARA_MARKER_PROP, "")).strip() == "1"
