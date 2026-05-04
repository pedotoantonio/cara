"""add device_permissions table — smart-home auth (Step 5.8)

Revision ID: a7b9c1e3d245
Revises: d6e2f9a4d825
Create Date: 2026-05-04 11:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b9c1e3d245"
down_revision: str | None = "d6e2f9a4d825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_permissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entity_pattern", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "entity_pattern", "action",
            name="device_permissions_unique_per_user_pattern_action",
        ),
    )
    op.create_index(
        "ix_device_permissions_user_id", "device_permissions", ["user_id"],
        unique=False,
    )
    op.create_index(
        "device_permissions_pattern", "device_permissions", ["entity_pattern"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("device_permissions_pattern", table_name="device_permissions")
    op.drop_index("ix_device_permissions_user_id", table_name="device_permissions")
    op.drop_table("device_permissions")
