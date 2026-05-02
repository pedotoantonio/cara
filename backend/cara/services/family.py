"""Family presence service — wraps the frigate-faces HTTP API.

frigate-faces (running at FRIGATE_FACES_URL) catalogues faces seen by the
house cameras and exposes a JSON list of `people` with a `last_seen`
timestamp. We expose a higher-level "who is home now" view by filtering
that list to people seen within a configurable window.

The caller never reaches frigate-faces directly: CARA owns the abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from cara.config import settings

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class PersonSeen:
    name: str
    last_seen: datetime
    minutes_ago: int


class FamilyPresenceUnavailable(RuntimeError):
    """Raised when the upstream face service is not reachable."""


def _parse_iso(s: str) -> datetime | None:
    # frigate-faces emits "YYYY-MM-DDTHH:MM:SS.ffffff" (naive). Treat as UTC.
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _normalise_name(name: str) -> str:
    # frigate-faces sometimes has duplicates with different casing
    # (e.g. "ilaria" / "Ilaria"). Title-case for display.
    return name.strip().title()


async def people_present(
    *, window_minutes: int | None = None
) -> list[PersonSeen]:
    """Return people seen within the last `window_minutes`. The list is
    deduplicated by name (keeping the most recent sighting per name).
    """
    if not settings.frigate_faces_url:
        raise FamilyPresenceUnavailable("frigate-faces not configured")
    window = window_minutes or settings.family_presence_window_minutes
    cutoff = datetime.now(UTC) - timedelta(minutes=window)

    url = f"{settings.frigate_faces_url.rstrip('/')}/api/people"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            rows: list[dict[str, Any]] = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("family.frigate_faces_unreachable", error=str(exc), url=url)
        raise FamilyPresenceUnavailable(f"frigate-faces unreachable: {exc}") from exc

    # Best-recent per normalised name within the window.
    best: dict[str, PersonSeen] = {}
    now = datetime.now(UTC)
    for row in rows:
        last = _parse_iso(row.get("last_seen") or "")
        if last is None or last < cutoff:
            continue
        name = _normalise_name(row.get("name") or "")
        if not name:
            continue
        minutes = max(int((now - last).total_seconds() // 60), 0)
        seen = PersonSeen(name=name, last_seen=last, minutes_ago=minutes)
        prior = best.get(name)
        if prior is None or seen.last_seen > prior.last_seen:
            best[name] = seen

    return sorted(best.values(), key=lambda p: p.last_seen, reverse=True)
