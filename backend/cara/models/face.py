"""ORM models for the client-side face recognition feature (Phase 1).

The browser computes 128-D descriptors via face-api.js and ships them
here; the backend stores them and (Phase 2 onward) serves them back to
new devices for offline matching. No raw images ever cross this layer.

Three tables:

- `face_profiles`    : the people who have explicitly consented to be
                       recognised.
- `face_descriptors` : the 128-D vectors for each profile, both from
                       enrollment (the 5 wizard captures) and from
                       continuous learning.
- `face_settings`    : a single-row table with the global kill-switch
                       and the default match threshold.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class FaceProfile(Base):
    __tablename__ = "face_profiles"
    __table_args__ = (
        Index(
            "idx_face_profiles_active_name",
            "display_name",
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_child: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    match_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    consent_given_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_text_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_recognized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recognition_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class FaceDescriptor(Base):
    __tablename__ = "face_descriptors"
    __table_args__ = (
        CheckConstraint(
            "source IN ('enrollment', 'continuous')",
            name="ck_face_descriptors_source",
        ),
        Index(
            "idx_face_descriptors_profile_created",
            "profile_id",
            text("created_at DESC"),
        ),
        # HNSW index for cosine-distance nearest-neighbor lookup (Phase 2
        # server-side match). Created with raw SQL in the migration; this
        # declaration just keeps `alembic check` from suggesting a drop.
        Index(
            "idx_face_descriptors_hnsw",
            "descriptor",
            postgresql_using="hnsw",
            postgresql_ops={"descriptor": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("face_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    descriptor: Mapped[list[float]] = mapped_column(Vector(128), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FaceSettings(Base):
    """Singleton settings table. The CHECK enforces a single row."""

    __tablename__ = "face_settings"
    __table_args__ = (CheckConstraint("id = true", name="ck_face_settings_singleton"),)

    id: Mapped[bool] = mapped_column(Boolean, primary_key=True, server_default="true")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    default_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    expression_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    age_gender_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
