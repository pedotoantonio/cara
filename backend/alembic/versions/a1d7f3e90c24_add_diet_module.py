"""Add CARA Nutrizione (diet) module — 7 tables.

Personalised diet module driven by a real meal plan (Dott.ssa Elena
Poletti). The plan reasons by *weekly frequencies* of protein
categories + *raw portions*, NOT by calorie counting — kcal are a
secondary/indicative metric. See `cara.diet` for the seed derived from
the source PDFs.

Tables:
  * diet_plans          — one active plan per user, links the source PDF
  * diet_rules          — editable targets/portions/context-rules per plan
  * food_items          — catalog with status + protein category + portions
  * meal_logs           — what the user actually ate (free text + parsed)
  * daily_intake        — per-day water_ml + coffee_count counters
  * weekly_summaries    — materialised Mon→Sun rollups + adherence score
  * recipes             — seeded with the pancake recipe

Revision ID: a1d7f3e90c24
Revises: d3a7b8c92f15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1d7f3e90c24"
down_revision = "d3a7b8c92f15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── diet_plans ────────────────────────────────────────────────
    op.create_table(
        "diet_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        # Version string = sha256 prefix of the source PDF set, so a
        # re-seed from a new plan bumps the version without duplicating.
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("source_document_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "version", name="uq_diet_plans_user_version"),
    )

    # ─── diet_rules (EDITABLE from UI) ─────────────────────────────
    op.create_table(
        "diet_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("diet_plans.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # category: protein cats (legumi|pesce|carne|uova|formaggio),
        # context rules (pizza_piadina|dolce|aperitivo|patate_polenta|
        # ristorante|allenamento_serale), intake (acqua|caffe|olio) or
        # free-text guideline (indicazione).
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("target_min", sa.Float(), nullable=True),
        sa.Column("target_max", sa.Float(), nullable=True),
        # period the target refers to: "week" | "day" | null (textual rule)
        sa.Column("period", sa.String(16), nullable=True),
        sa.Column("portion_primo_g", sa.Integer(), nullable=True),
        sa.Column("portion_secondo_g", sa.Integer(), nullable=True),
        sa.Column("portion_note", sa.Text(), nullable=True),
        sa.Column("kcal_estimate", sa.Integer(), nullable=True),
        sa.UniqueConstraint("plan_id", "category", name="uq_diet_rules_plan_category"),
    )

    # ─── food_items ────────────────────────────────────────────────
    op.create_table(
        "food_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        # consigliato | da_moderare | sconsigliato
        sa.Column("status", sa.String(16), nullable=False),
        # legumi|pesce|carne|uova|formaggio or NULL (carb / veg / fruit / condiment)
        sa.Column("protein_category", sa.String(16), nullable=True, index=True),
        sa.Column("default_portion_g", sa.Integer(), nullable=True),
        # Per-food portion overrides for the primo/secondo distinction
        # (cheeses, affettati, molluschi differ from the category rule).
        sa.Column("portion_primo_g", sa.Integer(), nullable=True),
        sa.Column("portion_secondo_g", sa.Integer(), nullable=True),
        # kcal_per_100g — EXTERNAL enrichment (CREA food-composition
        # table), NOT from the dietista PDF. See notes for provenance.
        sa.Column("kcal_per_100g", sa.Integer(), nullable=True),
        # season_months — EXTERNAL enrichment (conventional IT seasonal
        # calendar), NOT from the PDF (which groups fruit by portion only).
        sa.Column("season_months", postgresql.ARRAY(sa.Integer), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    # ─── meal_logs ─────────────────────────────────────────────────
    op.create_table(
        "meal_logs",
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
        # colazione | spuntino | pranzo | cena
        sa.Column("meal_type", sa.String(16), nullable=False),
        sa.Column("free_text", sa.Text(), nullable=True),
        sa.Column(
            "parsed_items",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("est_kcal", sa.Integer(), nullable=True),
        # The dominant protein category of the meal (for fast week rollups).
        sa.Column("protein_category", sa.String(16), nullable=True),
        sa.Column(
            "context_flags",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ─── daily_intake ──────────────────────────────────────────────
    op.create_table(
        "daily_intake",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("water_ml", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coffee_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "day", name="uq_daily_intake_user_day"),
    )

    # ─── weekly_summaries ──────────────────────────────────────────
    op.create_table(
        "weekly_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),  # Monday
        sa.Column("week_end", sa.Date(), nullable=False),    # Sunday
        sa.Column(
            "totals",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("adherence_score", sa.Float(), nullable=True),
        sa.Column("report_pdf_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "week_start", name="uq_weekly_summaries_user_week"
        ),
    )

    # ─── recipes ───────────────────────────────────────────────────
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column(
            "ingredients",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("steps", sa.Text(), nullable=True),
        sa.Column("source", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("recipes")
    op.drop_table("weekly_summaries")
    op.drop_table("daily_intake")
    op.drop_table("meal_logs")
    op.drop_table("food_items")
    op.drop_table("diet_rules")
    op.drop_table("diet_plans")
