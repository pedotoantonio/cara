"""reminders + reminder_templates + reminder_notifications

Revision ID: e7a9c2b5d301
Revises: d3e4a92f17c8
Create Date: 2026-05-20 10:00:00.000000

Memorial ondata: una surface dedicata ai "promemoria umani" (visita
medica, compleanno, scadenza carta d'identità, evento scuola figli).
Distinta da `tasks` — non vogliamo inquinare il task manager con item
ricorrenti che hanno UX e defaults completamente diversi.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "e7a9c2b5d301"
down_revision = "d3e4a92f17c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminder_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("category", sa.String(32), nullable=False, index=True),
        sa.Column("title_it", sa.String(200), nullable=False),
        sa.Column("icon", sa.String(16), nullable=False, server_default=""),
        sa.Column("fields", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("default_lead_times", postgresql.ARRAY(sa.Integer),
                  nullable=False, server_default=sa.text("ARRAY[]::int[]")),
        sa.Column("default_recurrence", sa.String(32), nullable=True),
        sa.Column("order_in_category", sa.Integer, nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("family_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("template_slug", sa.String(64), nullable=True),
        sa.Column("category", sa.String(32), nullable=False, index=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("recurrence", sa.String(32), nullable=True),
        sa.Column("recurrence_until", sa.Date, nullable=True),
        sa.Column("lead_times", postgresql.ARRAY(sa.Integer),
                  nullable=False, server_default=sa.text("ARRAY[]::int[]")),
        # NB: no server_default here — sa.text() would treat ":true" as
        # a bound parameter. The ORM-side default
        # (`lambda: {"push": True, "telegram": True}`) covers new rows.
        sa.Column("channels", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active", index=True),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_reminders_user_due", "reminders", ["user_id", "due_at"])

    op.create_table(
        "reminder_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("reminder_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("reminders.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),  # "pre_<minutes>" or "due"
        sa.Column("delivery", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("reminder_id", "kind", "scheduled_at",
                            name="uq_reminder_notif_kind_time"),
    )


def downgrade() -> None:
    op.drop_table("reminder_notifications")
    op.drop_index("ix_reminders_user_due", table_name="reminders")
    op.drop_table("reminders")
    op.drop_table("reminder_templates")
