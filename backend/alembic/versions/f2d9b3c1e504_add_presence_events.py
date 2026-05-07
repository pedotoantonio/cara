"""add presence_events table

Revision ID: f2d9b3c1e504
Revises: e9c7d3a8f415
Create Date: 2026-05-07 06:50:00.000000

Tracks every face/motion arrival that passed the cooldown filter in
the new `presence` agent. One row per debounced sighting, with the
notification fan-out flags so we know which channels actually fired.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "f2d9b3c1e504"
down_revision = "e9c7d3a8f415"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "presence_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("sighting_id", sa.Integer(), nullable=True),
        sa.Column("person_id", sa.Integer(), nullable=True),
        sa.Column("person_name", sa.String(length=80), nullable=False),
        sa.Column("camera_id", sa.String(length=40), nullable=False),
        sa.Column("is_known", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("snapshot_url", sa.String(length=500), nullable=True),
        sa.Column("notified_push", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notified_telegram", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("spoken_aloud", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("extra", JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint("sighting_id", name="uq_presence_events_sighting"),
    )
    op.create_index("ix_presence_events_seen_at", "presence_events", ["seen_at"])
    op.create_index(
        "ix_presence_events_person_seen",
        "presence_events",
        ["person_name", "seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_presence_events_person_seen", table_name="presence_events")
    op.drop_index("ix_presence_events_seen_at", table_name="presence_events")
    op.drop_table("presence_events")
