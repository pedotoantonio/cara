"""Thin httpx proxy over the frigate-faces admin API.

frigate-faces is the source of truth for the face DB; CARA never
duplicates it. This module wraps the few endpoints we need so the
`/api/v1/admin/persons` router can stay declarative.

Failures are returned as None / empty list — the caller turns that
into a 503 / 502 for the admin UI.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from cara.config import settings


log = structlog.get_logger(__name__)

_TIMEOUT = httpx.Timeout(8.0, connect=3.0)


def _base_url() -> str | None:
    url = (settings.frigate_faces_url or "").rstrip("/")
    return url or None


async def list_people() -> list[dict[str, Any]]:
    base = _base_url()
    if not base:
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(f"{base}/api/people")
            r.raise_for_status()
            return r.json() or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("frigate_faces.list_people.failed", error=str(exc))
        return []


async def get_person(person_id: int) -> dict[str, Any] | None:
    base = _base_url()
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(f"{base}/api/people/{person_id}")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("frigate_faces.get_person.failed", id=person_id, error=str(exc))
        return None


async def create_person(name: str, *, notify: bool = True) -> dict[str, Any] | None:
    base = _base_url()
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{base}/api/people",
                json={"name": name, "notify": 1 if notify else 0},
            )
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("frigate_faces.create_person.failed", name=name, error=str(exc))
        return None


async def update_person(
    person_id: int,
    *,
    name: str | None = None,
    notify: bool | None = None,
) -> dict[str, Any] | None:
    base = _base_url()
    if not base:
        return None
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if notify is not None:
        payload["notify"] = 1 if notify else 0
    if not payload:
        return await get_person(person_id)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.patch(f"{base}/api/people/{person_id}", json=payload)
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("frigate_faces.update_person.failed", id=person_id, error=str(exc))
        return None


async def delete_person(person_id: int) -> bool:
    base = _base_url()
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.delete(f"{base}/api/people/{person_id}")
            return r.status_code in (200, 204, 404)
    except httpx.HTTPError as exc:
        log.warning("frigate_faces.delete_person.failed", id=person_id, error=str(exc))
        return False


async def upload_face_image(
    person_id: int,
    *,
    filename: str,
    mime_type: str,
    blob: bytes,
) -> dict[str, Any] | None:
    base = _base_url()
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as c:
            r = await c.post(
                f"{base}/api/people/{person_id}/images",
                files={"image": (filename, blob, mime_type)},
            )
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("frigate_faces.upload_image.failed", id=person_id, error=str(exc))
        return None


async def fetch_image_blob(filename: str) -> tuple[bytes, str] | None:
    """Download a face/sighting image from frigate-faces and return
    the raw bytes + content-type. Used by the admin photo proxy in
    `cara.api.v1.persons` so the browser only ever talks to CARA on
    port 8455 (avoids extra cert prompts on :8452 + CORS gotchas).
    """
    base = _base_url()
    if not base or not filename:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as c:
            r = await c.get(f"{base}/api/image/{filename}")
            if r.status_code != 200:
                return None
            return r.content, r.headers.get("content-type", "image/jpeg")
    except httpx.HTTPError as exc:
        log.warning("frigate_faces.fetch_image.failed", file=filename, error=str(exc))
        return None


async def get_unknown_sighting(sighting_id: int) -> dict[str, Any] | None:
    """Look up one unknown sighting by id (returns whatever the
    frigate-faces /api/unknown gives us — image filename, camera,
    timestamp, etc.). frigate-faces doesn't expose a per-id endpoint
    for unknowns, so we filter the list. Cheap (small list)."""
    base = _base_url()
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(f"{base}/api/unknown")
            r.raise_for_status()
            rows = r.json() or []
    except (httpx.HTTPError, ValueError):
        return None
    for row in rows:
        try:
            if int(row.get("id") or 0) == int(sighting_id):
                return row
        except (TypeError, ValueError):
            continue
    return None


async def list_unknown_sightings(*, limit: int = 50) -> list[dict[str, Any]]:
    base = _base_url()
    if not base:
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(f"{base}/api/unknown")
            if r.status_code == 404:
                return []
            r.raise_for_status()
            rows = r.json() or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("frigate_faces.list_unknowns.failed", error=str(exc))
        return []
    # Normalise frigate-faces' shape (image_path / timestamp / camera)
    # into what `UnknownSightingOut` expects, and cap at `limit` since
    # the upstream endpoint doesn't honour a query param.
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        out.append({
            "id": row.get("id"),
            "camera": row.get("camera"),
            "timestamp": row.get("timestamp") or row.get("created_at"),
            "image_url": row.get("image_path"),
            "image_path": row.get("image_path"),
        })
    return out


async def ignore_sighting(sighting_id: int) -> bool:
    """Tell frigate-faces this unknown sighting is noise (not a face,
    or one we don't care about). Removes it from the unknowns queue
    so it doesn't keep showing up."""
    base = _base_url()
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(f"{base}/api/ignore/{sighting_id}")
            return r.status_code in (200, 204, 404)
    except httpx.HTTPError as exc:
        log.warning(
            "frigate_faces.ignore_sighting.failed",
            sighting_id=sighting_id, error=str(exc),
        )
        return False


async def assign_sighting(sighting_id: int, person_id: int) -> bool:
    """Assign an unknown sighting to an existing person id. We resolve
    the id → name first because frigate-faces' `/api/identify` accepts
    {sighting_id, name} and looks up / creates the person by name."""
    base = _base_url()
    if not base:
        return False
    person = await get_person(person_id)
    name = (person or {}).get("name") if person else None
    if not name:
        log.warning("frigate_faces.assign_sighting.unknown_person", id=person_id)
        return False
    return await identify_sighting_with_name(sighting_id, str(name))


async def identify_sighting_with_name(sighting_id: int, name: str) -> bool:
    """Tell frigate-faces "this sighting is <name>". The endpoint
    auto-creates the person row if the name is new and auto-matches
    other unknowns with similar face encoding (built-in)."""
    base = _base_url()
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{base}/api/identify",
                json={"sighting_id": int(sighting_id), "name": name.strip()},
            )
            return r.status_code in (200, 204)
    except httpx.HTTPError as exc:
        log.warning(
            "frigate_faces.identify.failed",
            sighting_id=sighting_id, error=str(exc),
        )
        return False
