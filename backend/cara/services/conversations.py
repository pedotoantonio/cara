"""Conversation/message persistence helpers (scoped by user_id)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cara.models import Conversation, Message


async def create_conversation(
    session: AsyncSession, *, user_id: int, title: str | None = None
) -> Conversation:
    convo = Conversation(user_id=user_id, title=title or "Nuova conversazione")
    session.add(convo)
    await session.flush()
    return convo


async def list_conversations(
    session: AsyncSession, *, user_id: int, limit: int = 50
) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID, *, user_id: int
) -> Conversation | None:
    stmt = (
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .options(selectinload(Conversation.messages))
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def delete_conversation(
    session: AsyncSession, conversation_id: uuid.UUID, *, user_id: int
) -> bool:
    convo = await get_conversation(session, conversation_id, user_id=user_id)
    if convo is None:
        return False
    await session.delete(convo)
    return True


async def add_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    token_count: int | None = None,
    latency_ms: int | None = None,
    first_token_ms: int | None = None,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        token_count=token_count,
        latency_ms=latency_ms,
        first_token_ms=first_token_ms,
    )
    session.add(msg)
    await session.flush()
    return msg


async def history_for_prompt(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    limit: int = 8,
) -> list[Message]:
    """Return the last `limit` messages for prompt rendering.

    Ordering rules:
    - The system message (the persona seed, if any) is always first.
    - The remaining user/assistant turns follow in chronological order.

    We can't rely solely on `created_at ASC` because all messages persisted in
    the same DB transaction share the same timestamp (Postgres `now()` is
    statement-time): without this explicit rule, a freshly seeded system
    message could end up after the first user message in the prompt.
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    rows.reverse()
    rows.sort(key=lambda m: (0 if m.role == "system" else 1, m.created_at))
    return rows
