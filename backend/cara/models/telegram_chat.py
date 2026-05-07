"""TelegramChatMapping — per-chat persisted state.

Replaces the in-memory `_chat_to_convo` dict in
`cara.integrations.telegram` so:
  - the bot survives backend restarts without losing the chat ↔ user
    binding (`/start` doesn't have to be re-issued, conversations
    keep their UUID);
  - the admin UI (`/admin/telegram`) can list mapped chats, add new
    family members, toggle per-chat notifications without restarting.

Bootstrap allowlist `CARA_TELEGRAM_CHAT_OWNERS` is still respected
(env-var owners can't be removed via UI) — this table EXTENDS it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class TelegramChatMapping(Base):
    __tablename__ = "telegram_chat_mappings"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    voice_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
