"""Note ORM model — quick personal notes / markdown memos."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Nota senza titolo")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # NOTE: no `onupdate=func.now()` — quel pattern mette la colonna in
    # "refresh-required" dopo flush, e in async SQLAlchemy il lazy reload
    # → MissingGreenlet alla serializzazione Pydantic. Aggiorniamo
    # esplicitamente nel service `update_note`. Stesso bug già risolto
    # su Reminders (vedi CLAUDE.md "Quirks di implementazione").
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
