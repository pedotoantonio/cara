"""add tool_call_metrics table — tool calling telemetry (Step 0.4)

Revision ID: e8a2c5f7b310
Revises: d4e1f8b3a201
Create Date: 2026-05-04 09:45:00.000000

One row per tool-call attempt. Substrate for the admin "what's actually
breaking" diagnostics page. See `cara/models/tool_metric.py` for design.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8a2c5f7b310"
down_revision: str | None = "d4e1f8b3a201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_call_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("parse_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("name_match", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("args_valid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("executed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tool_name", sa.String(length=80), nullable=True),
        sa.Column("error_class", sa.String(length=40), nullable=True),
        sa.Column("raw_call", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("tool_metrics_ts", "tool_call_metrics", ["ts"], unique=False)
    op.create_index(
        "tool_metrics_tool_ts", "tool_call_metrics", ["tool_name", "ts"], unique=False
    )
    op.create_index(
        "tool_metrics_user_ts", "tool_call_metrics", ["user_id", "ts"], unique=False
    )
    op.create_index(
        "ix_tool_call_metrics_error_class",
        "tool_call_metrics",
        ["error_class"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tool_call_metrics_error_class", table_name="tool_call_metrics")
    op.drop_index("tool_metrics_user_ts", table_name="tool_call_metrics")
    op.drop_index("tool_metrics_tool_ts", table_name="tool_call_metrics")
    op.drop_index("tool_metrics_ts", table_name="tool_call_metrics")
    op.drop_table("tool_call_metrics")
