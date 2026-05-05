"""add events table — episodic memory (Step 0.3)

Revision ID: d4e1f8b3a201
Revises: c8a7d94e1f02
Create Date: 2026-05-04 09:30:00.000000

Append-only event log. Replaces the in-memory ring buffer in
`cara.services.event_log`. See `cara/models/event.py` for the design notes.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e1f8b3a201"
down_revision: str | None = "c8a7d94e1f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("ref_id", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("events_user_ts", "events", ["user_id", "ts"], unique=False)
    op.create_index("events_kind_ts", "events", ["kind", "ts"], unique=False)
    op.create_index("events_ref_ts", "events", ["ref_id", "ts"], unique=False)


def downgrade() -> None:
    op.drop_index("events_ref_ts", table_name="events")
    op.drop_index("events_kind_ts", table_name="events")
    op.drop_index("events_user_ts", table_name="events")
    op.drop_table("events")
