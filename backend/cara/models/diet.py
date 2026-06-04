"""CARA Nutrizione (diet) ORM models.

Seven tables backing the personalised diet module. The plan reasons by
*weekly frequencies* of protein categories + *raw portions* (grammature
a crudo, al netto degli scarti). Calories are secondary/indicative.

Provenance contract:
  * Rules / portions / frequencies / status lists  → the dietista PDFs
    (`cara.diet.catalog`, transcribed faithfully — single source of truth).
  * `food_items.season_months`                     → conventional IT
    seasonal calendar (external enrichment, marked in notes).
  * `food_items.kcal_per_100g`                      → CREA food-composition
    table (external enrichment, marked in notes).

See migration `a1d7f3e90c24`.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base

# ─── Vocabularies (frozen for MVP) ─────────────────────────────────

STATUS_CONSIGLIATO = "consigliato"
STATUS_DA_MODERARE = "da_moderare"
STATUS_SCONSIGLIATO = "sconsigliato"
STATUSES = (STATUS_CONSIGLIATO, STATUS_DA_MODERARE, STATUS_SCONSIGLIATO)

# The five colored protein categories the plan tracks by frequency.
PROTEIN_CATEGORIES = ("legumi", "pesce", "carne", "uova", "formaggio")

# Plan colors (from the PDF, page 12). Used by the week-bars UI.
CATEGORY_COLORS = {
    "legumi": "#22c55e",     # verde
    "pesce": "#38bdf8",      # azzurro
    "carne": "#d946ef",      # magenta
    "uova": "#3b82f6",       # blu
    "formaggio": "#eab308",  # giallo
}

MEAL_TYPES = ("colazione", "spuntino", "pranzo", "cena")


class DietPlan(Base):
    __tablename__ = "diet_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # sha256 prefix of the source PDF set — re-seeding the same PDFs is a
    # no-op; a new plan PDF bumps the version (new row, old deactivated).
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    source_document_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_diet_plans_user_version"),
    )


class DietRule(Base):
    """Editable target/portion/context rule for a plan.

    `category` covers protein cats, context rules and intake limits.
    `period` is "week" (frequency), "day" (intake) or NULL (textual
    guideline). Editable from the admin/settings UI — a new dietista
    visit changes data here, never code.
    """

    __tablename__ = "diet_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("diet_plans.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    target_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    portion_primo_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portion_secondo_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portion_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    kcal_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("plan_id", "category", name="uq_diet_rules_plan_category"),
    )


class FoodItem(Base):
    __tablename__ = "food_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    protein_category: Mapped[str | None] = mapped_column(
        String(16), nullable=True, index=True
    )
    default_portion_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Coarse classification (frutta|verdura|cereale|proteina|latticini|
    # condimento|dolce|bevanda|frutta_secca|altro). Drives fruit/veg
    # counting and intake breakdowns; robust replacement for portion
    # heuristics. Added by migration b2e8c4f1a937.
    food_group: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Per-food overrides of the category portion (cheeses/affettati/molluschi).
    portion_primo_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portion_secondo_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # EXTERNAL enrichment (CREA) — indicative, not from the dietista plan.
    kcal_per_100g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # EXTERNAL enrichment (IT seasonal calendar) — not from the plan.
    season_months: Mapped[list[int] | None] = mapped_column(
        ARRAY(Integer), nullable=True
    )
    # EXTERNAL enrichment (Open Food Facts) — packaged products resolved by
    # barcode scan get cached here so a re-scan is instant and offline.
    barcode: Mapped[str | None] = mapped_column(
        String(14), nullable=True, unique=True, index=True
    )
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class MealLog(Base):
    __tablename__ = "meal_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    meal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # List of {food, portion_g, protein_category, status} dicts from the parser.
    parsed_items: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    est_kcal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protein_category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # {pizza_piadina: true, dolce: true, allenamento_serale: true, ...}
    context_flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DailyIntake(Base):
    __tablename__ = "daily_intake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    water_ml: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    coffee_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "day", name="uq_daily_intake_user_day"),
    )


class WeeklySummary(Base):
    __tablename__ = "weekly_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)  # Monday
    week_end: Mapped[date] = mapped_column(Date, nullable=False)    # Sunday
    totals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    adherence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    report_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "week_start", name="uq_weekly_summaries_user_week"),
    )


# Activity factors (Mifflin-St Jeor / standard TDEE multipliers).
ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "very": 1.725,
    "extra": 1.9,
}

# Default daily kcal delta per goal (negative = deficit ≈ 0.5 kg/week).
GOAL_DEFAULT_DELTA = {"maintain": 0, "lose": -500, "gain": 300}


class DietProfile(Base):
    """Per-user anthropometrics for energy needs (Mifflin-St Jeor BMR)."""

    __tablename__ = "diet_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    sex: Mapped[str | None] = mapped_column(String(1), nullable=True)  # M | F
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="moderate", server_default="moderate"
    )
    goal: Mapped[str] = mapped_column(
        String(12), nullable=False, default="maintain", server_default="maintain"
    )
    goal_rate_kcal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # NB: updated_at set explicitly in the service (no onupdate → avoids the
    # async MissingGreenlet refresh bug, same as reminders).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExerciseLog(Base):
    """A logged workout. kcal_burned = MET × weight_kg × hours."""

    __tablename__ = "exercise_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    activity: Mapped[str] = mapped_column(String(80), nullable=False)
    met: Mapped[float] = mapped_column(Float, nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    kcal_burned: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    ingredients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
