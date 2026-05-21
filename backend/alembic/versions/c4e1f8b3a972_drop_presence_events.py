"""drop presence_events table

Revision ID: c4e1f8b3a972
Revises: e7f4c2a18b5d
Create Date: 2026-05-13 09:00:00.000000

The legacy `presence` agent (polled frigate-faces every 30 s and wrote
a row per arrival) has been removed. Presence is now driven entirely
client-side via the face-api.js stack; nothing writes to this table
anymore and no surface reads from it.

The downgrade re-creates the table empty.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "c4e1f8b3a972"
down_revision = "e7f4c2a18b5d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("presence_events")


def downgrade() -> None:
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
        sa.Column("telegram_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("push_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ws_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("meta", JSONB(), nullable=True),
        sa.UniqueConstraint("sighting_id", name="uq_presence_events_sighting_id"),
    )
    op.create_index(
        "idx_presence_events_seen_at",
        "presence_events",
        ["seen_at"],
    )
