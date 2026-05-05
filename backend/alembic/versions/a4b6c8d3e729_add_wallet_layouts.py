"""add wallet_layouts table (Step 7.4)

Revision ID: a4b6c8d3e729
Revises: f8a2b1c4e527
Create Date: 2026-05-04 14:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4b6c8d3e729"
down_revision: str | None = "f8a2b1c4e527"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wallet_layouts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("surface_class", sa.String(length=20), nullable=False),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("preset", sa.String(length=40), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "surface_class",
            name="wallet_layouts_unique_per_user_surface",
        ),
    )
    op.create_index(
        "ix_wallet_layouts_user_id", "wallet_layouts", ["user_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_wallet_layouts_user_id", table_name="wallet_layouts")
    op.drop_table("wallet_layouts")
