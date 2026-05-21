"""add users.tone_preference

Revision ID: a1c5e8d29f74
Revises: e7a9c2b5d301
Create Date: 2026-05-21 09:00:00.000000

Lumo-conversion Ondata α #1 — per-user voice tone override.

NULL = inherit `admin_settings.tone_preset` (which itself defaults to
"default"). Valid values are runtime-validated against
`_chat_prompt.USER_SELECTABLE_TONES`; we don't enforce a CHECK so admin
can register new tones via TONE_DIRECTIVE without a migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a1c5e8d29f74"
down_revision = "e7a9c2b5d301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tone_preference", sa.String(length=24), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "tone_preference")
