"""add workflow_trust table (Step 3.8)

Revision ID: f8a2b1c4e527
Revises: e2bc7a1f8d34
Create Date: 2026-05-04 14:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8a2b1c4e527"
down_revision: str | None = "e2bc7a1f8d34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_trust",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workflow_kind", sa.String(length=40), nullable=False),
        sa.Column("action_signature", sa.String(length=200), nullable=False),
        sa.Column(
            "confirms_streak", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "revoked", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "workflow_kind", "action_signature",
            name="workflow_trust_unique_per_user_kind_signature",
        ),
    )
    op.create_index(
        "ix_workflow_trust_user_id", "workflow_trust", ["user_id"], unique=False,
    )
    op.create_index(
        "workflow_trust_user_kind", "workflow_trust",
        ["user_id", "workflow_kind"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("workflow_trust_user_kind", table_name="workflow_trust")
    op.drop_index("ix_workflow_trust_user_id", table_name="workflow_trust")
    op.drop_table("workflow_trust")
