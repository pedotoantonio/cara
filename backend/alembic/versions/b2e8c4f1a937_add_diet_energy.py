"""Add diet energy tracking: profiles, exercise logs, food_group.

Adds the calorie side of CARA Nutrizione (still secondary to frequencies):
  * diet_profiles  — per-user anthropometrics for BMR/TDEE (Mifflin-St Jeor)
  * exercise_logs  — logged sport with MET → kcal burned
  * food_items.food_group — robust classification (frutta/verdura/…),
    fixes fruit counting and feeds intake breakdowns.

Revision ID: b2e8c4f1a937
Revises: a1d7f3e90c24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2e8c4f1a937"
down_revision = "a1d7f3e90c24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # food classification (frutta|verdura|cereale|proteina|latticini|
    # condimento|dolce|bevanda|frutta_secca|altro)
    op.add_column(
        "food_items", sa.Column("food_group", sa.String(20), nullable=True)
    )

    op.create_table(
        "diet_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("sex", sa.String(1), nullable=True),         # 'M' | 'F'
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        # sedentary|light|moderate|very|extra
        sa.Column(
            "activity_level", sa.String(16), nullable=False, server_default="moderate"
        ),
        # maintain|lose|gain
        sa.Column("goal", sa.String(12), nullable=False, server_default="maintain"),
        # explicit daily kcal delta for the goal (negative = deficit). NULL =
        # use the default for the chosen goal.
        sa.Column("goal_rate_kcal", sa.Integer(), nullable=True),
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

    op.create_table(
        "exercise_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
        sa.Column("activity", sa.String(80), nullable=False),
        sa.Column("met", sa.Float(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("kcal_burned", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("exercise_logs")
    op.drop_table("diet_profiles")
    op.drop_column("food_items", "food_group")
