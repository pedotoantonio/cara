"""add persona_profiles

Revision ID: b2d6f9a47e15
Revises: a1c5e8d29f74
Create Date: 2026-05-21 10:00:00.000000

Lumo-conversion Ondata β — per-user longitudinal profile built by
map-reduce LLM (EXTRACT + MERGE prompts) over Conversation history.

One row per user; the unique constraint is the natural PK (user_id).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "b2d6f9a47e15"
down_revision = "a1c5e8d29f74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persona_profiles",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "markdown",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("last_message_id_consumed", sa.Integer(), nullable=True),
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("last_status", sa.String(length=24), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column(
            "last_built_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("persona_profiles")
