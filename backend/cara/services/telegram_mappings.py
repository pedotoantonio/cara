"""CRUD over the `telegram_chat_mappings` table.

The Telegram bot reads from this service when resolving chat_id →
User; the admin UI calls the same service via REST to add / remove /
toggle family members at runtime.

Resolution precedence in `cara.integrations.telegram._resolve_user_for_chat`:
  1. DB row in `telegram_chat_mappings` (admin-managed)
  2. env-var `CARA_TELEGRAM_CHAT_USER_MAP` bootstrap mapping

Bootstrap is read-only at the env layer; the admin can shadow / extend
it via DB rows but can't delete env-mapped chats this way.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models import TelegramChatMapping, User


log = structlog.get_logger(__name__)


async def list_mappings(session: AsyncSession) -> list[TelegramChatMapping]:
    rows = (
        await session.execute(
            select(TelegramChatMapping).order_by(TelegramChatMapping.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def get_by_chat_id(
    session: AsyncSession, chat_id: int,
) -> TelegramChatMapping | None:
    return await session.get(TelegramChatMapping, chat_id)


async def create_or_update(
    session: AsyncSession,
    *,
    chat_id: int,
    user_id: int,
    label: str | None = None,
    notifications_enabled: bool | None = None,
    voice_enabled: bool | None = None,
) -> TelegramChatMapping:
    row = await session.get(TelegramChatMapping, chat_id)
    if row is None:
        row = TelegramChatMapping(
            chat_id=chat_id,
            user_id=user_id,
            label=label,
            notifications_enabled=(
                True if notifications_enabled is None else bool(notifications_enabled)
            ),
            voice_enabled=(
                True if voice_enabled is None else bool(voice_enabled)
            ),
        )
        session.add(row)
    else:
        row.user_id = user_id
        if label is not None:
            row.label = label
        if notifications_enabled is not None:
            row.notifications_enabled = bool(notifications_enabled)
        if voice_enabled is not None:
            row.voice_enabled = bool(voice_enabled)
    await session.flush()
    return row


async def delete(session: AsyncSession, chat_id: int) -> bool:
    row = await session.get(TelegramChatMapping, chat_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def set_conversation(
    session: AsyncSession, chat_id: int, conversation_id: uuid.UUID,
) -> None:
    """Stash the persistent CARA Conversation UUID for this chat. Idempotent."""
    await session.execute(
        update(TelegramChatMapping)
        .where(TelegramChatMapping.chat_id == chat_id)
        .values(
            conversation_id=conversation_id,
            last_active_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()


async def clear_conversation(session: AsyncSession, chat_id: int) -> None:
    """`/reset` from the bot — drops the conversation pointer so the
    next message creates a fresh one. The mapping itself stays."""
    await session.execute(
        update(TelegramChatMapping)
        .where(TelegramChatMapping.chat_id == chat_id)
        .values(conversation_id=None)
    )
    await session.flush()


async def touch(session: AsyncSession, chat_id: int) -> None:
    """Update `last_active_at` so the admin UI can sort by recency."""
    await session.execute(
        update(TelegramChatMapping)
        .where(TelegramChatMapping.chat_id == chat_id)
        .values(last_active_at=datetime.now(timezone.utc))
    )
    await session.flush()


async def chat_ids_with_notifications(session: AsyncSession) -> list[int]:
    """Used by `cara.services.notify._send_telegram` to filter out chats
    that turned notifications off."""
    rows = (
        await session.execute(
            select(TelegramChatMapping.chat_id).where(
                TelegramChatMapping.notifications_enabled.is_(True)
            )
        )
    ).scalars().all()
    return list(rows)
