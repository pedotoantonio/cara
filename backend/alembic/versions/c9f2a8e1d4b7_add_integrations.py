"""add integrations: oauth_credentials + calendar_events + email_proposals + email_learning_signals

Revision ID: c9f2a8e1d4b7
Revises: b8e3f5a2c1d4
Create Date: 2026-05-05 11:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c9f2a8e1d4b7"
down_revision: str | None = "b8e3f5a2c1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- oauth_credentials ----
    op.create_table(
        "oauth_credentials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("scope_set", sa.String(length=120), nullable=False),
        sa.Column("access_token", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account_email", sa.String(length=255), nullable=False),
        sa.Column(
            "config_json", postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}", nullable=False,
        ),
        sa.Column(
            "revoked", sa.Boolean(),
            server_default=sa.text("false"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", "scope_set", "account_email",
            name="uq_oauth_user_provider_scope_email",
        ),
    )
    op.create_index(
        "ix_oauth_credentials_user_id", "oauth_credentials", ["user_id"],
    )

    # ---- calendar_events ----
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("calendar_id", sa.String(length=160), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("recurrence_rule", sa.Text(), nullable=True),
        sa.Column(
            "all_day", sa.Boolean(),
            server_default=sa.text("false"), nullable=False,
        ),
        sa.Column(
            "attendees", postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}", nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("etag", sa.String(length=120), nullable=True),
        sa.Column(
            "last_pulled_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("linked_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["linked_task_id"], ["tasks.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "external_id",
            name="uq_calendar_provider_external",
        ),
    )
    op.create_index(
        "ix_calendar_events_user_id", "calendar_events", ["user_id"],
    )
    op.create_index(
        "ix_calendar_events_user_start",
        "calendar_events", ["user_id", "start_at"],
    )

    # Add calendar_external_id column to tasks (for outbound push tracking).
    op.add_column(
        "tasks",
        sa.Column("calendar_external_id", sa.String(length=120), nullable=True),
    )

    # ---- email_proposals ----
    op.create_table(
        "email_proposals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=120), nullable=False),
        sa.Column("from_address", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("proposal_type", sa.String(length=40), nullable=False),
        sa.Column(
            "proposal_args", postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}", nullable=False,
        ),
        sa.Column(
            "confidence", sa.Float(),
            server_default="0", nullable=False,
        ),
        sa.Column("source_layer", sa.String(length=20), nullable=False),
        sa.Column(
            "status", sa.String(length=20),
            server_default="pending", nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_action", postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "message_id",
            name="uq_email_proposal_user_msg",
        ),
    )
    op.create_index(
        "ix_email_proposals_user_id", "email_proposals", ["user_id"],
    )
    op.create_index(
        "ix_email_proposals_user_status",
        "email_proposals", ["user_id", "status"],
    )

    # ---- email_learning_signals ----
    op.create_table(
        "email_learning_signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("signal_type", sa.String(length=40), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.Column(
            "accepts", sa.Integer(),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "rejects", sa.Integer(),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "signal_type", "pattern",
            name="uq_email_learning_user_pattern",
        ),
    )
    op.create_index(
        "ix_email_learning_signals_user_id",
        "email_learning_signals", ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_learning_signals_user_id", table_name="email_learning_signals")
    op.drop_table("email_learning_signals")
    op.drop_index("ix_email_proposals_user_status", table_name="email_proposals")
    op.drop_index("ix_email_proposals_user_id", table_name="email_proposals")
    op.drop_table("email_proposals")
    op.drop_column("tasks", "calendar_external_id")
    op.drop_index("ix_calendar_events_user_start", table_name="calendar_events")
    op.drop_index("ix_calendar_events_user_id", table_name="calendar_events")
    op.drop_table("calendar_events")
    op.drop_index("ix_oauth_credentials_user_id", table_name="oauth_credentials")
    op.drop_table("oauth_credentials")
