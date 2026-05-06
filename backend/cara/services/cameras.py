"""Camera service — wraps Frigate NVR for the admin UI and the family
presence pipeline.

Frigate is the source of truth for the camera list (defined in its own
YAML config). CARA only stores per-camera overrides — display label,
area binding, "presence_relevant" flag, motion-notification flag — in
`admin_settings["cameras"]`.

Two read paths:
- `list_cameras()` — admin "Telecamere" panel: Frigate camera ids merged
  with CARA's overrides + last-frame snapshot URLs.
- `recent_person_events()` — used by `family/who-is-home` as a fallback
  when no face match was seen recently: "vedo movimento ma non riconosco
  il volto".

All HTTP calls swallow errors and return empty / sensible defaults — the
chat layer must never 500 because Frigate is down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cara.config import settings
from cara.services import admin_settings as admin_svc

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(4.0, connect=2.0)


@dataclass(slots=True)
class Camera:
    """A camera as seen by CARA: Frigate's id + admin-set metadata."""

    id: str                       # Frigate camera id (e.g. "cam_194")
    label: str                    # "Ingresso" — shown in the UI
    area: str | None              # "ingresso" — smart-home area binding
    presence_relevant: bool       # counts toward "chi è in casa"
    notify_motion: bool           # push Telegram on motion event
    online: bool                  # last_recording_time within ~2 minutes
    last_seen: datetime | None    # last frigate-reported recording
    snapshot_url: str | None      # absolute URL of the latest frame
    objects: list[str]            # detection object set ("person", ...)


@dataclass(slots=True)
class PersonEvent:
    """A `person` event from Frigate /api/events."""

    camera: str
    start_time: datetime
    end_time: datetime | None


async def _frigate_url(session: AsyncSession) -> str:
    """Resolve Frigate NVR base URL, admin override > env default."""
    override = await admin_svc.get(session, "frigate_url")
    return (override or settings.frigate_url or "").rstrip("/")


async def _camera_overrides(session: AsyncSession) -> dict[str, dict[str, Any]]:
    raw = await admin_svc.get(session, "cameras")
    if not isinstance(raw, dict):
        return {}
    return raw  # already keyed by camera id


def _label_for(cam_id: str, override: dict[str, Any] | None) -> str:
    if override and isinstance(override.get("label"), str) and override["label"].strip():
        return override["label"].strip()
    # Fallback: humanise "cam_194" → "Cam 194".
    return cam_id.replace("_", " ").title()


async def list_cameras(session: AsyncSession) -> list[Camera]:
    """Fetch the live camera list from Frigate, merge with admin overrides."""
    base = await _frigate_url(session)
    if not base:
        return []
    overrides = await _camera_overrides(session)

    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            r_cfg = await client.get(f"{base}/api/config")
            r_cfg.raise_for_status()
            cfg = r_cfg.json()
            # Frigate /api/stats includes a per-camera dict with
            # last_recording_time (epoch seconds). Failures here just
            # leave online=False / last_seen=None.
            try:
                r_stats = await client.get(f"{base}/api/stats")
                r_stats.raise_for_status()
                stats = r_stats.json()
            except httpx.HTTPError:
                stats = {}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("cameras.frigate_unreachable", url=base, error=str(exc))
        return []

    now = datetime.now(UTC)
    out: list[Camera] = []
    cameras_cfg: dict[str, dict[str, Any]] = cfg.get("cameras") or {}
    for cam_id, _cam_cfg in cameras_cfg.items():
        ovr = overrides.get(cam_id) or {}
        # last_recording_time is at stats[cam_id]["last_recording_time"]
        # in Frigate ≥0.13. Older versions expose it differently.
        cam_stats = stats.get(cam_id) or {}
        last_ts = cam_stats.get("last_recording_time")
        last_seen: datetime | None = None
        if isinstance(last_ts, (int, float)) and last_ts > 0:
            last_seen = datetime.fromtimestamp(last_ts, tz=UTC)
        online = bool(last_seen and (now - last_seen).total_seconds() < 120)
        objects = list((cfg.get("objects") or {}).get("track") or ["person"])
        out.append(
            Camera(
                id=cam_id,
                label=_label_for(cam_id, ovr),
                area=ovr.get("area"),
                presence_relevant=bool(ovr.get("presence_relevant", True)),
                notify_motion=bool(ovr.get("notify_motion", False)),
                online=online,
                last_seen=last_seen,
                snapshot_url=f"{base}/api/{cam_id}/latest.jpg" if online else None,
                objects=objects,
            )
        )
    out.sort(key=lambda c: (not c.presence_relevant, c.label))
    return out


async def update_camera_override(
    session: AsyncSession,
    camera_id: str,
    *,
    actor_user_id: int | None = None,
    label: str | None = None,
    area: str | None = None,
    presence_relevant: bool | None = None,
    notify_motion: bool | None = None,
) -> dict[str, Any]:
    """Persist a per-camera CARA override. Returns the merged record.

    The Frigate camera list is the source of truth — we never CREATE a
    camera here, only attach metadata. If `camera_id` is unknown to
    Frigate the call still succeeds (admins may want to pre-configure
    cameras before they appear in Frigate).
    """
    raw = await admin_svc.get(session, "cameras")
    overrides: dict[str, dict[str, Any]] = (
        dict(raw) if isinstance(raw, dict) else {}
    )
    current = dict(overrides.get(camera_id) or {})
    if label is not None:
        current["label"] = label.strip() or None
        if current["label"] is None:
            current.pop("label", None)
    if area is not None:
        current["area"] = area.strip() or None
        if current["area"] is None:
            current.pop("area", None)
    if presence_relevant is not None:
        current["presence_relevant"] = bool(presence_relevant)
    if notify_motion is not None:
        current["notify_motion"] = bool(notify_motion)
    overrides[camera_id] = current
    await admin_svc.set(
        session, "cameras", overrides, actor_user_id=actor_user_id
    )
    return current


async def recent_person_events(
    session: AsyncSession,
    *,
    window_minutes: int,
) -> list[PersonEvent]:
    """Query Frigate /api/events for `person` detections in the last
    `window_minutes`. Used as a "movement seen but no face matched"
    fallback by the family presence service.
    """
    base = await _frigate_url(session)
    if not base:
        return []
    cutoff = datetime.now(UTC).timestamp() - (window_minutes * 60)
    params = {
        "label": "person",
        "after": cutoff,
        "limit": 50,
        "include_thumbnails": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            r = await client.get(f"{base}/api/events", params=params)
            r.raise_for_status()
            rows = r.json() or []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("cameras.frigate_events_unreachable", error=str(exc))
        return []

    overrides = await _camera_overrides(session)
    out: list[PersonEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cam_id = row.get("camera")
        if not cam_id:
            continue
        # Skip cameras the admin marked as not presence-relevant.
        ovr = overrides.get(cam_id)
        if ovr and ovr.get("presence_relevant") is False:
            continue
        try:
            start = datetime.fromtimestamp(float(row["start_time"]), tz=UTC)
        except (KeyError, TypeError, ValueError):
            continue
        end_ts = row.get("end_time")
        end = (
            datetime.fromtimestamp(float(end_ts), tz=UTC)
            if isinstance(end_ts, (int, float)) else None
        )
        out.append(PersonEvent(camera=cam_id, start_time=start, end_time=end))
    out.sort(key=lambda e: e.start_time, reverse=True)
    return out
