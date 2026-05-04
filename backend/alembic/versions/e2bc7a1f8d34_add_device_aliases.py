"""add device_aliases table (Step 5.4)

Revision ID: e2bc7a1f8d34
Revises: c5a8e0f4d619
Create Date: 2026-05-04 13:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2bc7a1f8d34"
down_revision: str | None = "c5a8e0f4d619"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.String(length=120), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.Column("area", sa.String(length=80), nullable=True),
        sa.Column("source_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_id", "alias",
            name="device_aliases_unique_per_entity_alias",
        ),
    )
    op.create_index(
        "device_aliases_entity", "device_aliases", ["entity_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("device_aliases_entity", table_name="device_aliases")
    op.drop_table("device_aliases")
