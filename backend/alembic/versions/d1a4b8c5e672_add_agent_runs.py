"""add agent_runs table

Revision ID: d1a4b8c5e672
Revises: c9f2a8e1d4b7
Create Date: 2026-05-06 21:00:00.000000

Tracks every Celery task execution from the new agent workers
(`mail`, `files`, `learn`). One row per task run, with idempotency
key to dedupe re-runs. Used by /admin/agents and /admin/diagnostics
to surface agent health.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "d1a4b8c5e672"
down_revision = "c9f2a8e1d4b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.String(length=40), nullable=False),
        sa.Column("task_name", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("payload", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_class", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "agent_name", "task_name", "idempotency_key",
            name="uq_agent_runs_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_runs_agent_started",
        "agent_runs",
        ["agent_name", "started_at"],
    )
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_started", table_name="agent_runs")
    op.drop_table("agent_runs")
