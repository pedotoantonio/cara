"""Notes endpoints — auth, user-scoped."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.schemas.note import NoteCreate, NoteOut, NoteUpdate
from cara.services import notes as svc
from cara.services.family_bus import publish as fb_publish
from cara.store import get_session

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=list[NoteOut])
async def list_notes(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[NoteOut]:
    rows = await svc.list_notes(session, user_id=user.id)
    return [NoteOut.model_validate(r) for r in rows]


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(
    body: NoteCreate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> NoteOut:
    note = await svc.create_note(
        session, user_id=user.id, title=body.title or "", body=body.body
    )
    out = NoteOut.model_validate(note)
    await fb_publish("note.created", user_id=user.id, payload=out.model_dump(mode="json"))
    return out


@router.get("/{note_id}", response_model=NoteOut)
async def get_note(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> NoteOut:
    note = await svc.get_note(session, note_id, user_id=user.id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    return NoteOut.model_validate(note)


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: uuid.UUID,
    body: NoteUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> NoteOut:
    note = await svc.update_note(
        session, note_id, user_id=user.id, title=body.title, body=body.body
    )
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    out = NoteOut.model_validate(note)
    await fb_publish("note.updated", user_id=user.id, payload=out.model_dump(mode="json"))
    return out


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await svc.delete_note(session, note_id, user_id=user.id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    await fb_publish("note.deleted", user_id=user.id, payload={"id": str(note_id)})
