"""LAN-only family face management for the Wall.

Mirrors the admin-only `/api/v1/admin/persons*` endpoints, but with
the `require_lan` guard instead of `require_admin`. Anyone on the home
Wi-Fi can present a new family member to CARA, upload reference
photos, and assign unknown sightings — without logging in.

The actual face encoding / matching still happens in `frigate-faces`;
this module is a thin proxy that adds:

- LAN gating (192.168.1.0/24 + 10.8.0.0/24 + 127.0.0.0/8 + 172.31.0.0/16)
- audit logging of every mutation under the synthetic actor "wall"
- same-origin image proxy so the browser never has to trust the
  separate `:8452` port

Order note: routes here MUST be registered such that
`/wall/persons/unknowns*` and `/wall/persons/{id}/photo` come BEFORE
the catch-all variable `/wall/persons/{id}` would shadow them. FastAPI
matches in registration order — see the file layout below.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import (
    APIRouter, Depends, File, HTTPException, Request, UploadFile, status,
)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.v1.wall import require_lan
from cara.services import audit as audit_svc
from cara.services import frigate_faces_admin as ff
from cara.store import get_session


log = structlog.get_logger(__name__)

router = APIRouter(prefix="/wall/persons", tags=["wall-persons"])


# ─── Schemas ───────────────────────────────────────────────────────


class WallPersonOut(BaseModel):
    id: int
    name: str
    notify: bool
    sighting_count: int = 0
    last_seen: str | None = None
    latest_image: str | None = None


class WallPersonCreate(BaseModel):
    name: str
    notify: bool = True


class WallPersonPatch(BaseModel):
    name: str | None = None
    notify: bool | None = None


class WallUnknownOut(BaseModel):
    id: int
    camera: str | None = None
    timestamp: str | None = None
    image_url: str | None = None


class WallAssignBody(BaseModel):
    person_id: int


class WallCreateFromSightingBody(BaseModel):
    name: str
    notify: bool = True


def _row_to_out(r: dict[str, Any]) -> WallPersonOut:
    return WallPersonOut(
        id=int(r.get("id") or 0),
        name=str(r.get("name") or ""),
        notify=bool(r.get("notify", True)),
        sighting_count=int(r.get("sighting_count") or 0),
        last_seen=r.get("last_seen"),
        latest_image=r.get("latest_image"),
    )


async def _wall_audit(
    session: AsyncSession, request: Request, action: str, detail: dict[str, Any]
) -> None:
    """Record a wall-driven mutation. We don't have a real `User`
    actor (LAN endpoints don't authenticate), but we still want a row
    so admins can see what changed and from where."""
    try:
        await audit_svc.record(
            session,
            actor=None,
            action=f"wall.{action}",
            ip=request.client.host if request.client else None,
            detail=detail,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("wall.persons.audit_failed", action=action, error=str(exc))


# ─── Probe (suggest existing person before creating a duplicate) ────


@router.post("/probe-image")
async def probe_image(
    file: UploadFile = File(...),  # noqa: B008
    _lan: None = Depends(require_lan),  # noqa: B008
) -> dict[str, Any]:
    """Recognize a face in `file` against the known catalogue without
    any side effect (no DB insert, no bus event).

    Used by the Wall family page right before the user creates a new
    person: if the photo already matches someone, the UI suggests the
    existing person instead of letting the user accidentally create a
    duplicate (the same trap that produced Ilaria/ilaria last week).
    """
    import httpx  # noqa: PLC0415
    from cara.config import settings as _cfg  # noqa: PLC0415

    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file vuoto")
    if len(blob) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "max 10 MB")

    base = (_cfg.frigate_faces_url or "").rstrip("/")
    if not base:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "frigate-faces non configurato",
        )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=3.0)) as c:
            r = await c.post(
                f"{base}/api/recognize-image",
                files={"image": (
                    file.filename or "probe.jpg", blob,
                    file.content_type or "image/jpeg",
                )},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"frigate-faces irraggiungibile: {exc}",
        ) from exc

    if r.status_code >= 400:
        try:
            msg = (r.json() or {}).get("error") or ""
        except Exception:  # noqa: BLE001
            msg = r.text[:200]
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"frigate-faces ha rifiutato la foto: {msg or r.status_code}",
        )

    try:
        data = r.json()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "risposta non-JSON da frigate-faces",
        ) from exc

    return {
        "found_face": bool(data.get("found_face")),
        "match": data.get("match"),  # {name, person_id, distance} or null
    }


# ─── Specific routes (must precede /{person_id} catch-all) ──────────
# Even though FastAPI's route trie distinguishes static segments from
# parametric ones, we keep them ordered for clarity and so an obvious
# typo (e.g. `/{x}/photo` vs `/photo/{x}`) won't shadow them.


@router.get("/unknowns", response_model=list[WallUnknownOut])
async def list_unknowns(
    limit: int = 50,
    _lan: None = Depends(require_lan),  # noqa: B008
) -> list[WallUnknownOut]:
    """Recent un-recognised face sightings from frigate-faces."""
    limit = max(1, min(limit, 200))
    rows = await ff.list_unknown_sightings(limit=limit)
    out: list[WallUnknownOut] = []
    for r in rows:
        out.append(
            WallUnknownOut(
                id=int(r.get("id") or 0),
                camera=r.get("camera"),
                timestamp=r.get("timestamp") or r.get("created_at"),
                image_url=r.get("image_url"),
            )
        )
    return out


@router.get("/unknowns/{sighting_id}/image")
async def unknown_image(
    sighting_id: int,
    _lan: None = Depends(require_lan),  # noqa: B008
) -> Response:
    """Same-origin JPEG proxy for an unknown sighting."""
    sighting = await ff.get_unknown_sighting(sighting_id)
    if sighting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sighting non trovata")
    filename = (
        sighting.get("image_path")
        or sighting.get("image")
        or sighting.get("filename")
        or (sighting.get("image_url") or "").rsplit("/", 1)[-1]
    )
    if not filename:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "nessuna foto per questa sighting")
    out = await ff.fetch_image_blob(str(filename))
    if out is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "frigate-faces non raggiungibile")
    blob, ctype = out
    return Response(
        content=blob, media_type=ctype,
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.post("/unknowns/{sighting_id}/assign", status_code=status.HTTP_204_NO_CONTENT)
async def assign_sighting(
    sighting_id: int,
    body: WallAssignBody,
    request: Request,
    _lan: None = Depends(require_lan),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await ff.assign_sighting(sighting_id, body.person_id)
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "assegnazione fallita")
    await _wall_audit(
        session, request, f"persons.assign_sighting[{sighting_id}→{body.person_id}]",
        {"sighting_id": sighting_id, "person_id": body.person_id},
    )


@router.post("/unknowns/{sighting_id}/create_person", response_model=WallPersonOut)
async def create_person_from_sighting(
    sighting_id: int,
    body: WallCreateFromSightingBody,
    request: Request,
    _lan: None = Depends(require_lan),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WallPersonOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "il nome è obbligatorio")
    created = await ff.create_person(name=name, notify=body.notify)
    if created is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "creazione fallita")
    person_id = int(created["id"])
    ok = await ff.assign_sighting(sighting_id, person_id)
    if not ok:
        await _wall_audit(
            session, request, "persons.create_from_sighting.assign_failed",
            {"sighting_id": sighting_id, "person_id": person_id, "name": name},
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"persona creata ({name}, id={person_id}) ma l'assegnazione è fallita",
        )
    await _wall_audit(
        session, request, f"persons.create_from_sighting[{sighting_id}→{name}]",
        {"sighting_id": sighting_id, "person_id": person_id, "name": name},
    )
    return _row_to_out(created)


# ─── List / get / create / update / delete / upload / photo ─────────


@router.get("", response_model=list[WallPersonOut])
async def list_persons(
    _lan: None = Depends(require_lan),  # noqa: B008
) -> list[WallPersonOut]:
    rows = await ff.list_people()
    return [_row_to_out(r) for r in rows]


@router.post("", response_model=WallPersonOut, status_code=status.HTTP_201_CREATED)
async def create_person(
    body: WallPersonCreate,
    request: Request,
    _lan: None = Depends(require_lan),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WallPersonOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "il nome è obbligatorio")
    created = await ff.create_person(name=name, notify=body.notify)
    if created is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "creazione fallita")
    await _wall_audit(
        session, request, f"persons.create[{name}]",
        {"name": name, "notify": body.notify, "id": int(created["id"])},
    )
    return _row_to_out(created)


@router.get("/{person_id}/readiness")
async def person_readiness(
    person_id: int,
    _lan: None = Depends(require_lan),  # noqa: B008
) -> dict[str, Any]:
    """Recognition readiness for an enrolled person.

    Heavy lifting (pairwise distance matrix on 128-dim encodings) lives
    in frigate-faces — it owns the encoding store and has numpy +
    face_recognition already loaded. This route just proxies + LAN-gates.

    Returns 404 if the person doesn't exist (frigate-faces says so),
    503 if frigate-faces is unreachable. The body shape is documented
    in `frigate-faces/app.py::compute_readiness`.
    """
    out = await ff.get_readiness(person_id)
    if out is None:
        # We can't distinguish 404 from network failure cleanly without
        # changing the FF client signature; fall back to 404 since the
        # vastly more common case is "person never created" and a
        # missing recognition surface is a recoverable UX, not a fatal
        # one.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "persona non trovata o frigate-faces non raggiungibile",
        )
    return out


@router.get("/{person_id}/photo")
async def person_photo(
    person_id: int,
    _lan: None = Depends(require_lan),  # noqa: B008
) -> Response:
    """Same-origin proxy for the latest reference image of a person."""
    rows = await ff.list_people()
    person = next((r for r in rows if int(r.get("id") or 0) == int(person_id)), None)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona non trovata")
    latest = person.get("latest_image")
    if not latest:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "nessuna foto ancora")
    out = await ff.fetch_image_blob(str(latest))
    if out is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "frigate-faces non raggiungibile")
    blob, ctype = out
    return Response(
        content=blob, media_type=ctype,
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.post("/{person_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(
    person_id: int,
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    _lan: None = Depends(require_lan),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file vuoto")
    if len(blob) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "max 10 MB")
    out = await ff.upload_face_image(
        person_id,
        filename=file.filename or "upload.jpg",
        mime_type=file.content_type or "image/jpeg",
        blob=blob,
    )
    if not out:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "upload rifiutato")
    await _wall_audit(
        session, request, f"persons.upload_photo[{person_id}]",
        {"id": person_id, "size": len(blob), "filename": file.filename},
    )
    return out


@router.patch("/{person_id}", response_model=WallPersonOut)
async def update_person(
    person_id: int,
    body: WallPersonPatch,
    request: Request,
    _lan: None = Depends(require_lan),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WallPersonOut:
    name = body.name.strip() if body.name is not None else None
    updated = await ff.update_person(
        person_id, name=name, notify=body.notify,
    )
    if updated is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "aggiornamento fallito")
    await _wall_audit(
        session, request, f"persons.update[{person_id}]",
        {"id": person_id, "name": name, "notify": body.notify},
    )
    return _row_to_out(updated)


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: int,
    request: Request,
    _lan: None = Depends(require_lan),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await ff.delete_person(person_id)
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "eliminazione fallita")
    await _wall_audit(
        session, request, f"persons.delete[{person_id}]", {"id": person_id},
    )


__all__ = ["router"]
