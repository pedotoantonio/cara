"""add budgets + expenses tables (Step 3.5)

Revision ID: c5a8e0f4d619
Revises: b5d4f1a82e36
Create Date: 2026-05-04 13:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5a8e0f4d619"
down_revision: str | None = "b5d4f1a82e36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("target_amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "year", "month", "category",
            name="budgets_unique_per_month_category",
        ),
    )
    op.create_index("budgets_year_month", "budgets", ["year", "month"], unique=False)

    op.create_table(
        "expenses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("spent_on", sa.Date(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("vendor", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("expenses_date", "expenses", ["spent_on"], unique=False)
    op.create_index(
        "expenses_category_date", "expenses", ["category", "spent_on"], unique=False,
    )
    op.create_index(
        "expenses_user_date", "expenses", ["user_id", "spent_on"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("expenses_user_date", table_name="expenses")
    op.drop_index("expenses_category_date", table_name="expenses")
    op.drop_index("expenses_date", table_name="expenses")
    op.drop_table("expenses")
    op.drop_index("budgets_year_month", table_name="budgets")
    op.drop_table("budgets")
