"""lifeops m1 — lists + list_items + pending_approvals + extend reminders + users.is_supervisor

Revision ID: c1f8a5d3e926
Revises: b2d6f9a47e15
Create Date: 2026-05-22 11:00:00.000000

LifeOps Milestone 1 — foundations:
- 3 nuove tabelle: lifeops_lists, lifeops_list_items,
  lifeops_pending_approvals
- ALTER reminders: source / urgent / delivery_context (additive,
  default safe per row esistenti)
- ALTER users: is_supervisor (backfilled per role='parent')
- Backfill ShoppingItem → LifeopsList('shopping')

Reversibile. Idempotente.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "c1f8a5d3e926"
down_revision = "b2d6f9a47e15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. users.is_supervisor (backfill: parent → true) ────────────────
    op.add_column(
        "users",
        sa.Column(
            "is_supervisor",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "UPDATE users SET is_supervisor = true WHERE role = 'parent'"
    )

    # ── 2. reminders extension ──────────────────────────────────────────
    # Additive: tutte le row esistenti restano valide.
    op.add_column(
        "reminders",
        sa.Column(
            "source",
            sa.String(length=24),
            nullable=False,
            server_default="template",
        ),
    )
    op.add_column(
        "reminders",
        sa.Column(
            "urgent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "reminders",
        sa.Column(
            "delivery_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # ── 3. lifeops_lists ───────────────────────────────────────────────
    op.create_table(
        "lifeops_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("family_id", sa.Integer(), nullable=True, index=True),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("icon", sa.String(length=32), nullable=True),
        sa.Column(
            "scope",
            sa.String(length=16),
            nullable=False,
            server_default="user",
        ),
        sa.Column("color_token", sa.String(length=32), nullable=True),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "slug", name="lifeops_list_user_slug_uq"),
    )
    op.create_index(
        "lifeops_list_family_idx", "lifeops_lists", ["family_id"]
    )

    # ── 4. lifeops_list_items ──────────────────────────────────────────
    op.create_table(
        "lifeops_list_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "list_id",
            sa.Integer(),
            sa.ForeignKey("lifeops_lists.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(length=280), nullable=False),
        sa.Column("qty", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=24), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "done",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "done_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "pending_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── 5. lifeops_pending_approvals ───────────────────────────────────
    op.create_table(
        "lifeops_pending_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "requested_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "supervisor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True, index=True),
        sa.Column(
            "target_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=280), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "lifeops_pending_state_idx",
        "lifeops_pending_approvals",
        ["state", "expires_at"],
    )

    # ── 6. Backfill ShoppingItem → lifeops_lists('shopping')────────────
    # Per ogni user con item in shopping_items, crea una lista 'shopping'
    # scope='family' e copia gli item.
    #
    # NB: usiamo SQL puro per evitare di importare ORM models a
    # migration time (rischio coupling con codice futuro).
    op.execute(
        """
        DO $$
        DECLARE
            uid INTEGER;
            new_list_id INTEGER;
            now_ts TIMESTAMPTZ := NOW();
        BEGIN
            -- Per ogni user con almeno un shopping_item
            FOR uid IN
                SELECT DISTINCT user_id FROM shopping_items
                WHERE NOT EXISTS (
                    SELECT 1 FROM lifeops_lists
                    WHERE user_id = shopping_items.user_id AND slug = 'shopping'
                )
            LOOP
                INSERT INTO lifeops_lists
                  (user_id, slug, title, icon, scope, color_token,
                   sort_order, created_at, updated_at)
                VALUES
                  (uid, 'shopping', 'Spesa', 'shopping-cart', 'family',
                   'rose-500', 0, now_ts, now_ts)
                RETURNING id INTO new_list_id;

                INSERT INTO lifeops_list_items
                  (list_id, user_id, title, qty, done, sort_order,
                   created_at, updated_at)
                SELECT
                    new_list_id,
                    user_id,
                    title,
                    CASE WHEN qty IS NOT NULL THEN qty::float ELSE NULL END,
                    bought,
                    0,
                    COALESCE(created_at, now_ts),
                    COALESCE(created_at, now_ts)
                FROM shopping_items
                WHERE user_id = uid;
            END LOOP;
        END$$;
        """
    )


def downgrade() -> None:
    # Backward order: drop lifeops first, then revert ALTER
    op.drop_index(
        "lifeops_pending_state_idx", table_name="lifeops_pending_approvals"
    )
    op.drop_table("lifeops_pending_approvals")
    op.drop_table("lifeops_list_items")
    op.drop_index("lifeops_list_family_idx", table_name="lifeops_lists")
    op.drop_table("lifeops_lists")

    op.drop_column("reminders", "delivery_context")
    op.drop_column("reminders", "urgent")
    op.drop_column("reminders", "source")

    op.drop_column("users", "is_supervisor")
