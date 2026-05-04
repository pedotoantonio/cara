"""add facts table — semantic memory (Step 2.2)

Revision ID: d6e2f9a4d825
Revises: f3c9d72e8b14
Create Date: 2026-05-04 10:45:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6e2f9a4d825"
down_revision: str | None = "f3c9d72e8b14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "facts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default=sa.text("1.0"),
        ),
        sa.Column(
            "embedding",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "first_seen", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "last_confirmed", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("source_ref", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("facts_user_active", "facts", ["user_id", "active"], unique=False)
    op.create_index("facts_type", "facts", ["type"], unique=False)
    op.create_index("facts_source", "facts", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index("facts_source", table_name="facts")
    op.drop_index("facts_type", table_name="facts")
    op.drop_index("facts_user_active", table_name="facts")
    op.drop_table("facts")
