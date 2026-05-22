"""lifeops m2 — finance: accounts, categories, transactions + seed 12 categorie

Revision ID: d3a7b8c92f15
Revises: c1f8a5d3e926
Create Date: 2026-05-22 18:00:00.000000

M2 LifeOps:
- lifeops_accounts (per-user)
- lifeops_finance_categories (per-family, seedate 12)
- lifeops_transactions (per-user, Numeric(12,2), state pending/confirmed/rejected)
- Seed idempotente delle 12 categorie italiane (family_id=NULL)
- Account 'Contanti' EUR per ogni user esistente

Reversibile.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "d3a7b8c92f15"
down_revision = "c1f8a5d3e926"
branch_labels = None
depends_on = None


# Catalogo seed — 12 categorie italiane realistiche
CATEGORIES_SEED = [
    ("casa", "Casa & utenze", "expense", "home", "slate-500"),
    ("spesa", "Spesa & alimentari", "expense", "shopping-cart", "emerald-500"),
    ("trasporti", "Trasporti & carburante", "expense", "car", "sky-500"),
    ("salute", "Salute & farmacia", "expense", "cross", "rose-500"),
    ("bimbi", "Bimbi & scuola", "expense", "child", "amber-500"),
    ("ristoranti", "Ristoranti & bar", "expense", "coffee", "orange-500"),
    ("tempo_libero", "Tempo libero", "expense", "popcorn", "violet-500"),
    ("abbonamenti", "Abbonamenti & servizi", "expense", "repeat", "indigo-500"),
    ("regali", "Regali & cerimonie", "expense", "gift", "pink-500"),
    ("altre_spese", "Altre spese", "expense", "dots", "zinc-500"),
    ("stipendio", "Stipendio & compensi", "income", "briefcase", "green-600"),
    ("entrate_varie", "Entrate varie", "income", "arrow-down", "green-500"),
]


def upgrade() -> None:
    # ── lifeops_accounts ──────────────────────────────────────────
    op.create_table(
        "lifeops_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="EUR",
        ),
        sa.Column(
            "balance_cents",
            sa.BigInteger(),
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
    )

    # ── lifeops_finance_categories ────────────────────────────────
    op.create_table(
        "lifeops_finance_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), nullable=True, index=True),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("icon", sa.String(length=32), nullable=True),
        sa.Column("color_token", sa.String(length=32), nullable=True),
        sa.Column(
            "is_system",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.UniqueConstraint(
            "family_id", "slug", name="lifeops_fincat_family_slug_uq"
        ),
    )

    # ── lifeops_transactions ──────────────────────────────────────
    op.create_table(
        "lifeops_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("lifeops_accounts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("lifeops_finance_categories.id"),
            nullable=True,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column(
            "happened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column("description", sa.String(length=280), nullable=True),
        sa.Column("raw_utterance", sa.Text(), nullable=True),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "lifeops_tx_user_when_idx",
        "lifeops_transactions",
        ["user_id", "happened_at"],
    )
    op.create_index(
        "lifeops_tx_state_idx", "lifeops_transactions", ["state"]
    )

    # ── Seed 12 categorie (single-family: family_id=NULL) ────────
    for slug, label, direction, icon, color in CATEGORIES_SEED:
        op.execute(
            sa.text(
                """
                INSERT INTO lifeops_finance_categories
                  (family_id, slug, label, direction, icon, color_token, is_system)
                SELECT NULL, :slug, :label, :direction, :icon, :color, 1
                WHERE NOT EXISTS (
                  SELECT 1 FROM lifeops_finance_categories
                  WHERE family_id IS NULL AND slug = :slug
                )
                """
            ).bindparams(
                slug=slug,
                label=label,
                direction=direction,
                icon=icon,
                color=color,
            )
        )

    # ── Account 'Contanti' per ogni user attivo ──────────────────
    op.execute(
        """
        INSERT INTO lifeops_accounts (user_id, name, kind, currency, balance_cents)
        SELECT id, 'Contanti', 'cash', 'EUR', 0
        FROM users
        WHERE is_active = true
          AND NOT EXISTS (
            SELECT 1 FROM lifeops_accounts
            WHERE lifeops_accounts.user_id = users.id
              AND lifeops_accounts.kind = 'cash'
          )
        """
    )


def downgrade() -> None:
    op.drop_index("lifeops_tx_state_idx", table_name="lifeops_transactions")
    op.drop_index("lifeops_tx_user_when_idx", table_name="lifeops_transactions")
    op.drop_table("lifeops_transactions")
    op.drop_table("lifeops_finance_categories")
    op.drop_table("lifeops_accounts")
