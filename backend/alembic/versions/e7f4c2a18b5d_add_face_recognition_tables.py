"""add face recognition tables (Phase 1)

Revision ID: e7f4c2a18b5d
Revises: b9e3f1c6d472
Create Date: 2026-05-13 06:30:00.000000

Phase 1 of the face-recognition feature. Adds:

- `face_profiles`        : enrolled identities (display name, child flag,
                           consent metadata, recognition stats)
- `face_descriptors`     : 128-D face-api.js descriptors stored as
                           `vector(128)` for nearest-neighbor search
                           via pgvector
- `face_settings`        : singleton settings row (kill-switch, default
                           threshold, optional expression / age-gender)

The descriptors themselves are biometric data under GDPR Art. 4(14).
We do not store raw photos: the browser keeps them locally in IndexedDB,
the backend only ever sees the 128 floats. Disk-level encryption at the
OS layer is the at-rest guard; a future hardening phase may wrap the
descriptor column with pgcrypto if regulators demand it.

The feature defaults to **disabled** in `face_settings`. Admin opt-in
required.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision = "e7f4c2a18b5d"
down_revision = "b9e3f1c6d472"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector is available on this DB (cara-postgres-pgvector image); make
    # sure the extension is installed in this database so vector(128) works.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "face_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("is_child", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("match_threshold", sa.Float, server_default="0.5", nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_text_version", sa.String(32), nullable=True),
        sa.Column("last_recognized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recognition_count", sa.Integer, server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_face_profiles_active_name",
        "face_profiles",
        ["display_name"],
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "face_descriptors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("face_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("descriptor", Vector(128), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("quality", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('enrollment', 'continuous')",
            name="ck_face_descriptors_source",
        ),
    )
    op.create_index(
        "idx_face_descriptors_profile_created",
        "face_descriptors",
        ["profile_id", sa.text("created_at DESC")],
    )
    # hnsw cosine index for server-side nearest-neighbor lookup (Phase 2).
    op.execute(
        "CREATE INDEX idx_face_descriptors_hnsw "
        "ON face_descriptors USING hnsw (descriptor vector_cosine_ops)"
    )

    # Singleton settings row. The CHECK on `id` enforces exactly one row.
    op.create_table(
        "face_settings",
        sa.Column("id", sa.Boolean, primary_key=True, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column(
            "default_threshold", sa.Float, server_default="0.5", nullable=False
        ),
        sa.Column(
            "expression_enabled", sa.Boolean, server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "age_gender_enabled", sa.Boolean, server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = true", name="ck_face_settings_singleton"),
    )
    op.execute("INSERT INTO face_settings (id) VALUES (true)")


def downgrade() -> None:
    op.drop_table("face_settings")
    op.execute("DROP INDEX IF EXISTS idx_face_descriptors_hnsw")
    op.drop_index("idx_face_descriptors_profile_created", table_name="face_descriptors")
    op.drop_table("face_descriptors")
    op.drop_index("idx_face_profiles_active_name", table_name="face_profiles")
    op.drop_table("face_profiles")
