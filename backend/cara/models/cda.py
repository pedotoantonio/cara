"""ORM models for the Content Discovery Agent (CDA).

See `/opt/cara/docs/cda-extension-spec.md` for the full design. Tables:

- `cda_content_items`    : the family knowledge base of discovered content
- `cda_query_log`        : every CDA invocation (analytics + preference inference)
- `cda_user_preferences` : preferences inferred from history
- `cda_domain_trust`     : per-domain reliability scores
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class CdaContentItem(Base):
    __tablename__ = "cda_content_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default="{}", nullable=False, default=dict
    )

    confidence_score: Mapped[float] = mapped_column(Float, server_default="0.5", nullable=False, default=0.5)
    success_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False, default=0)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False, default=True)

    discovered_via: Mapped[str | None] = mapped_column(String(64), nullable=True)
    discovered_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("query_normalized", "url", name="uq_cda_items_query_url"),
    )


class CdaQueryLog(Base):
    __tablename__ = "cda_query_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    raw_query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    resolved_content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cda_content_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CdaUserPreference(Base):
    __tablename__ = "cda_user_preferences"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    preference_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    preference_value: Mapped[str] = mapped_column(Text, primary_key=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False, default=0)
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CdaDomainTrust(Base):
    __tablename__ = "cda_domain_trust"

    domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    base_score: Mapped[float] = mapped_column(Float, server_default="0.5", nullable=False, default=0.5)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
