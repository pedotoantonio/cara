"""add habit_candidates table — habit detection (Step 8.4)

Revision ID: b5d4f1a82e36
Revises: a7b9c1e3d245
Create Date: 2026-05-04 11:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5d4f1a82e36"
down_revision: str | None = "a7b9c1e3d245"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "habit_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("hour_bucket", sa.Integer(), nullable=False),
        sa.Column(
            "pattern",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "first_seen", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "last_seen", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "kind", "weekday", "hour_bucket",
            name="habit_candidates_unique_per_user_kind_slot",
        ),
    )
    op.create_index(
        "ix_habit_candidates_user_id", "habit_candidates", ["user_id"], unique=False,
    )
    op.create_index(
        "habit_candidates_status", "habit_candidates", ["status"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("habit_candidates_status", table_name="habit_candidates")
    op.drop_index("ix_habit_candidates_user_id", table_name="habit_candidates")
    op.drop_table("habit_candidates")
