"""add push_subscriptions + tasks.reminded_at

Revision ID: b8e3f5a2c1d4
Revises: a4b6c8d3e729
Create Date: 2026-05-05 09:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b8e3f5a2c1d4"
down_revision: str | None = "a4b6c8d3e729"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=2048), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth_secret", sa.String(length=255), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
    )
    op.create_index(
        "ix_push_subscriptions_user_id",
        "push_subscriptions",
        ["user_id"],
    )
    op.add_column(
        "tasks",
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "reminded_at")
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
