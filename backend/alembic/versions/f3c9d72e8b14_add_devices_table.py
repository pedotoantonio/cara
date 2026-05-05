"""add devices table — multi-surface device registry (Step 6.3)

Revision ID: f3c9d72e8b14
Revises: e8a2c5f7b310
Create Date: 2026-05-04 10:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3c9d72e8b14"
down_revision: str | None = "e8a2c5f7b310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("friendly_name", sa.String(length=80), nullable=False),
        sa.Column("surface_class", sa.String(length=20), nullable=False),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("location", sa.String(length=80), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("device_token", sa.String(length=800), nullable=True),
        sa.Column("paired_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "paired_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["paired_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("devices_status", "devices", ["status"], unique=False)
    op.create_index("devices_surface", "devices", ["surface_class"], unique=False)


def downgrade() -> None:
    op.drop_index("devices_surface", table_name="devices")
    op.drop_index("devices_status", table_name="devices")
    op.drop_table("devices")
