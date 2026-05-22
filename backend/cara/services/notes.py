"""Note persistence helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models import Note


async def list_notes(session: AsyncSession, *, user_id: int) -> list[Note]:
    stmt = (
        select(Note).where(Note.user_id == user_id).order_by(Note.updated_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_note(
    session: AsyncSession, *, user_id: int, title: str, body: str = ""
) -> Note:
    note = Note(user_id=user_id, title=title or "Nota senza titolo", body=body)
    session.add(note)
    await session.flush()
    return note


async def get_note(
    session: AsyncSession, note_id: uuid.UUID, *, user_id: int
) -> Note | None:
    stmt = select(Note).where(Note.id == note_id, Note.user_id == user_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_note(
    session: AsyncSession,
    note_id: uuid.UUID,
    *,
    user_id: int,
    title: str | None = None,
    body: str | None = None,
) -> Note | None:
    note = await get_note(session, note_id, user_id=user_id)
    if note is None:
        return None
    if title is not None:
        note.title = title or "Nota senza titolo"
    if body is not None:
        note.body = body
    # Esplicito (no `onupdate=func.now()` sul modello — vedi commento nel
    # modello: MissingGreenlet su async se la colonna va refresh-required).
    note.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return note


async def delete_note(
    session: AsyncSession, note_id: uuid.UUID, *, user_id: int
) -> bool:
    note = await get_note(session, note_id, user_id=user_id)
    if note is None:
        return False
    await session.delete(note)
    return True
