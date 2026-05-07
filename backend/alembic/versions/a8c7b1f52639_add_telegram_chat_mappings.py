"""add telegram_chat_mappings

Revision ID: a8c7b1f52639
Revises: f2d9b3c1e504
Create Date: 2026-05-07 09:00:00.000000

Persists Telegram chat_id ↔ CARA user binding + per-chat conversation
UUID + notification toggles. Lets the admin add family members
(Sara / Ilaria / kids) at runtime without redeploying the backend
with new env vars.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "a8c7b1f52639"
down_revision = "f2d9b3c1e504"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_chat_mappings",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "notifications_enabled", sa.Boolean(),
            nullable=False, server_default="true",
        ),
        sa.Column(
            "voice_enabled", sa.Boolean(),
            nullable=False, server_default="true",
        ),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_telegram_chat_mappings_user_id",
        "telegram_chat_mappings",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_chat_mappings_user_id", table_name="telegram_chat_mappings")
    op.drop_table("telegram_chat_mappings")
