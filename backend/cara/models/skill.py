"""ORM model for the Skill Factory (v0.7).

A `Skill` is a versioned, JSON-defined recipe that composes registered
primitives into a deterministic pipeline. See
`/opt/cara/docs/skill-factory-extension-prompt.md` §4-5 for the full schema.

This first slice (Step 66) ships only the `skills` table. Embeddings
(`skill_intent_embeddings`) and run telemetry (`skill_runs`) come later.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    intent_examples: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    slot_extraction: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )  # pending | active | disabled
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    auto_authored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
