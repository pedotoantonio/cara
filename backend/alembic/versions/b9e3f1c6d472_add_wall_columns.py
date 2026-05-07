"""add wall surface columns

Revision ID: b9e3f1c6d472
Revises: a8c7b1f52639
Create Date: 2026-05-07 11:00:00.000000

Wall is a public surface (`/wall`) showing family agenda on a wall-mounted
display. Adds:
- users.wall_visible / wall_color / wall_emoji  → owner identity on Wall
- tasks.wall_visible                            → per-task opt-out
- calendar_events.wall_visible                  → per-event opt-out

The Wall reads from these so any record can be hidden from the public
display without affecting the authenticated app.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "b9e3f1c6d472"
down_revision = "a8c7b1f52639"
branch_labels = None
depends_on = None


# Stable palette: 8 vivid hues, used by ID order at backfill so the
# first 8 family users get distinct colors deterministically.
_PALETTE = (
    "#f59e0b", "#10b981", "#3b82f6", "#ef4444",
    "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
)


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "wall_visible", sa.Boolean(),
            nullable=False, server_default="true",
        ),
    )
    op.add_column(
        "users",
        sa.Column("wall_color", sa.String(length=7), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("wall_emoji", sa.String(length=8), nullable=True),
    )
    # Backfill colors deterministically by user id, and emoji from role.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, role FROM users ORDER BY id ASC")
    ).fetchall()
    role_to_emoji = {
        "parent": "👤", "teen": "🎒", "child": "🧸",
        "elder": "👴", "guest": "👋",
    }
    for idx, row in enumerate(rows):
        color = _PALETTE[idx % len(_PALETTE)]
        emoji = role_to_emoji.get(row.role, "👤")
        bind.execute(
            sa.text(
                "UPDATE users SET wall_color = :c, wall_emoji = :e WHERE id = :id"
            ),
            {"c": color, "e": emoji, "id": row.id},
        )
    # Guests are not on the Wall by default — common case is "amico in
    # visita, niente foto/dati su un display pubblico".
    bind.execute(
        sa.text("UPDATE users SET wall_visible = false WHERE role = 'guest'")
    )

    # ── tasks ────────────────────────────────────────────────────────
    op.add_column(
        "tasks",
        sa.Column(
            "wall_visible", sa.Boolean(),
            nullable=False, server_default="true",
        ),
    )

    # ── calendar_events ──────────────────────────────────────────────
    op.add_column(
        "calendar_events",
        sa.Column(
            "wall_visible", sa.Boolean(),
            nullable=False, server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("calendar_events", "wall_visible")
    op.drop_column("tasks", "wall_visible")
    op.drop_column("users", "wall_emoji")
    op.drop_column("users", "wall_color")
    op.drop_column("users", "wall_visible")
