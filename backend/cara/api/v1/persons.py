"""Admin endpoints for face recognition management.

Surfaces the frigate-faces admin API through CARA's auth layer + audit
log so the admin doesn't need to keep the separate frigate-faces UI
open. All endpoints require `require_admin`.

The actual face encoding / matching is done by frigate-faces; CARA
just adds:
- auth gating
- audit logging on every mutation
- Italian-first response shapes
- a unified place to expose unknowns + the merge / reassign flow
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import require_admin
from cara.models.user import User
from cara.services import audit as audit_svc
from cara.services import frigate_faces_admin as ff
from cara.store import get_session


router = APIRouter(prefix="/admin/persons", tags=["admin-persons"])


# ─── Schemas ───────────────────────────────────────────────────────────


class PersonOut(BaseModel):
    id: int
    name: str
    notify: bool
    sighting_count: int = 0
    last_seen: str | None = None
    latest_image: str | None = None


class PersonCreate(BaseModel):
    name: str
    notify: bool = True


class PersonPatch(BaseModel):
    name: str | None = None
    notify: bool | None = None


class UnknownSightingOut(BaseModel):
    id: int
    camera: str | None = None
    timestamp: str | None = None
    image_url: str | None = None


class AssignSightingBody(BaseModel):
    person_id: int


class CreateFromSightingBody(BaseModel):
    name: str
    notify: bool = True


# ─── List / get / create / update / delete ────────────────────────────


@router.get("", response_model=list[PersonOut])
async def list_persons(
    _admin: User = Depends(require_admin),  # noqa: B008
) -> list[PersonOut]:
    rows = await ff.list_people()
    return [
        PersonOut(
            id=int(r["id"]),
            name=str(r.get("name", "")),
            notify=bool(r.get("notify", 1)),
            sighting_count=int(r.get("sighting_count", 0) or 0),
            last_seen=r.get("last_seen"),
            latest_image=r.get("latest_image"),
        )
        for r in rows
    ]


@router.post("", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
async def create_person(
    body: PersonCreate,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PersonOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "name required")
    created = await ff.create_person(name=name, notify=body.notify)
    if created is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "frigate-faces unavailable")
    await audit_svc.record(
        session,
        actor=admin,
        action=f"persons.create[{name}]",
        ip=request.client.host if request.client else None,
        detail={"name": name, "notify": body.notify},
    )
    await session.commit()
    return PersonOut(
        id=int(created["id"]),
        name=str(created.get("name", name)),
        notify=bool(created.get("notify", body.notify)),
        sighting_count=int(created.get("sighting_count", 0) or 0),
        last_seen=created.get("last_seen"),
        latest_image=created.get("latest_image"),
    )


@router.patch("/{person_id}", response_model=PersonOut)
async def update_person(
    person_id: int,
    body: PersonPatch,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PersonOut:
    updated = await ff.update_person(
        person_id, name=body.name, notify=body.notify
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")
    await audit_svc.record(
        session,
        actor=admin,
        action=f"persons.update[{person_id}]",
        ip=request.client.host if request.client else None,
        detail=body.model_dump(exclude_none=True),
    )
    await session.commit()
    return PersonOut(
        id=int(updated["id"]),
        name=str(updated.get("name", "")),
        notify=bool(updated.get("notify", 1)),
        sighting_count=int(updated.get("sighting_count", 0) or 0),
        last_seen=updated.get("last_seen"),
        latest_image=updated.get("latest_image"),
    )


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: int,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await ff.delete_person(person_id)
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "delete failed")
    await audit_svc.record(
        session,
        actor=admin,
        action=f"persons.delete[{person_id}]",
        ip=request.client.host if request.client else None,
        detail={"id": person_id},
    )
    await session.commit()


@router.post("/{person_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(
    person_id: int,
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    if len(blob) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "max 10 MB")
    out = await ff.upload_face_image(
        person_id,
        filename=file.filename or "face.jpg",
        mime_type=file.content_type or "image/jpeg",
        blob=blob,
    )
    if out is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "upload failed")
    await audit_svc.record(
        session,
        actor=admin,
        action=f"persons.photo[{person_id}]",
        ip=request.client.host if request.client else None,
        detail={"id": person_id, "size": len(blob)},
    )
    await session.commit()
    return out


# ─── Unknown sightings ────────────────────────────────────────────────


@router.get("/unknowns", response_model=list[UnknownSightingOut])
async def list_unknowns(
    limit: int = 50,
    _admin: User = Depends(require_admin),  # noqa: B008
) -> list[UnknownSightingOut]:
    limit = max(1, min(limit, 200))
    rows = await ff.list_unknown_sightings(limit=limit)
    out: list[UnknownSightingOut] = []
    for r in rows:
        out.append(
            UnknownSightingOut(
                id=int(r.get("id") or 0),
                camera=r.get("camera"),
                timestamp=r.get("timestamp") or r.get("created_at"),
                image_url=r.get("image_url"),
            )
        )
    return out


@router.post("/unknowns/{sighting_id}/assign", status_code=status.HTTP_204_NO_CONTENT)
async def assign_sighting(
    sighting_id: int,
    body: AssignSightingBody,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await ff.assign_sighting(sighting_id, body.person_id)
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "assign failed")
    await audit_svc.record(
        session,
        actor=admin,
        action=f"persons.assign_sighting[{sighting_id}→{body.person_id}]",
        ip=request.client.host if request.client else None,
        detail={"sighting_id": sighting_id, "person_id": body.person_id},
    )
    await session.commit()


@router.post("/unknowns/{sighting_id}/create_person", response_model=PersonOut)
async def create_person_from_sighting(
    sighting_id: int,
    body: CreateFromSightingBody,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PersonOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "name required")
    created = await ff.create_person(name=name, notify=body.notify)
    if created is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "create failed")
    person_id = int(created["id"])
    ok = await ff.assign_sighting(sighting_id, person_id)
    if not ok:
        # Person was created — audit it even if the assign fails so the
        # admin can recover manually from the unknowns list.
        await audit_svc.record(
            session, actor=admin,
            action=f"persons.create_from_sighting.partial[{name}]",
            ip=request.client.host if request.client else None,
            detail={"sighting_id": sighting_id, "person_id": person_id, "assign": False},
        )
        await session.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "person created but assignment failed",
        )
    await audit_svc.record(
        session, actor=admin,
        action=f"persons.create_from_sighting[{name}]",
        ip=request.client.host if request.client else None,
        detail={"sighting_id": sighting_id, "person_id": person_id},
    )
    await session.commit()
    return PersonOut(
        id=person_id,
        name=name,
        notify=body.notify,
        sighting_count=1,
        last_seen=created.get("last_seen"),
        latest_image=created.get("latest_image"),
    )
