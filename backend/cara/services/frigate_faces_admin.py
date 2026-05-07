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


async def list_unknown_sightings(*, limit: int = 50) -> list[dict[str, Any]]:
    base = _base_url()
    if not base:
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(f"{base}/api/sightings/unknown?limit={limit}")
            if r.status_code == 404:
                return []
            r.raise_for_status()
            return r.json() or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("frigate_faces.list_unknowns.failed", error=str(exc))
        return []


async def assign_sighting(sighting_id: int, person_id: int) -> bool:
    base = _base_url()
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{base}/api/sightings/{sighting_id}/assign",
                json={"person_id": person_id},
            )
            return r.status_code in (200, 204)
    except httpx.HTTPError as exc:
        log.warning(
            "frigate_faces.assign_sighting.failed",
            sighting_id=sighting_id, error=str(exc),
        )
        return False
