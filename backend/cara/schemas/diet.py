"""Pydantic schemas for the CARA Nutrizione (diet) module."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

# ─── Catalog / rules ───────────────────────────────────────────────


class FoodItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    protein_category: str | None
    food_group: str | None
    default_portion_g: int | None
    portion_primo_g: int | None
    portion_secondo_g: int | None
    kcal_per_100g: int | None
    season_months: list[int] | None
    notes: str | None


class DietRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    category: str
    target_min: float | None
    target_max: float | None
    period: str | None
    portion_primo_g: int | None
    portion_secondo_g: int | None
    portion_note: str | None
    kcal_estimate: int | None


class DietRuleUpdate(BaseModel):
    """Editable fields for a rule (admin/UI). All optional → patch."""

    target_min: float | None = None
    target_max: float | None = None
    period: str | None = None
    portion_primo_g: int | None = None
    portion_secondo_g: int | None = None
    portion_note: str | None = None
    kcal_estimate: int | None = None


class RecipeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    ingredients: list
    steps: str | None
    source: str | None


# ─── Meal logging ──────────────────────────────────────────────────


class ParsedItem(BaseModel):
    food: str
    portion_g: int | None = None
    protein_category: str | None = None
    food_group: str | None = None
    status: str | None = None


class MealLogIn(BaseModel):
    free_text: str = Field(..., min_length=1, max_length=1000)
    meal_type: str | None = Field(
        default=None, description="colazione|spuntino|pranzo|cena; inferred if omitted"
    )
    logged_at: datetime | None = None


class MealLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    logged_at: datetime
    meal_type: str
    free_text: str | None
    parsed_items: list
    est_kcal: int | None
    protein_category: str | None
    context_flags: dict


class MealLogResult(BaseModel):
    """POST /diet/log response — the saved row + parser warnings."""

    log: MealLogOut
    warnings: list[str] = Field(default_factory=list)
    carb_present: bool = False
    vegetable_present: bool = False
    fruit_present: bool = False


# ─── Today view ────────────────────────────────────────────────────


class TodayMealSlot(BaseModel):
    meal_type: str
    done: bool
    logs: list[MealLogOut] = Field(default_factory=list)


class TodayOut(BaseModel):
    day: date
    slots: list[TodayMealSlot]
    missing: list[str]
    water_ml: int
    water_target_min: int
    water_target_max: int
    coffee_count: int
    coffee_max: int
    fruit_servings: int
    fruit_target_min: int


# ─── Week / frequencies ────────────────────────────────────────────


class CategoryProgress(BaseModel):
    category: str
    color: str
    consumed: float
    target_min: float | None
    target_max: float | None
    state: str  # ok | under | over | warn


class WeekOut(BaseModel):
    week_start: date
    week_end: date
    categories: list[CategoryProgress]
    adherence_score: float
    avg_kcal_per_day: int | None
    avg_water_ml: int | None
    avg_coffee: float | None
    notes: list[str] = Field(default_factory=list)


# ─── Suggestions ───────────────────────────────────────────────────


class DishSuggestion(BaseModel):
    title: str
    covers_category: str | None
    detail: str


class SuggestOut(BaseModel):
    meal_type: str
    suggestions: list[DishSuggestion]
    under_target: list[str]
    warnings: list[str]
    context_reminders: list[str]
    speak_text: str


# ─── Intake counters ───────────────────────────────────────────────


class WaterIn(BaseModel):
    ml: int = Field(default=250, ge=0, le=3000)


class CoffeeIn(BaseModel):
    count: int = Field(default=1, ge=-5, le=10)


class IntakeOut(BaseModel):
    day: date
    water_ml: int
    coffee_count: int


# ─── Weekly report ─────────────────────────────────────────────────


class WeeklyReportOut(BaseModel):
    week_start: date
    week_end: date
    pdf_url: str | None
    telegram_text: str
    sent_to_telegram: bool


# ─── Energy: profile / exercise / stats ────────────────────────────


class DietProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sex: str | None
    birth_date: date | None
    height_cm: float | None
    weight_kg: float | None
    activity_level: str
    goal: str
    goal_rate_kcal: int | None
    # Derived (computed, not stored):
    age: int | None = None
    bmr: int | None = None
    tdee: int | None = None
    daily_target: int | None = None
    complete: bool = False


class DietProfileUpdate(BaseModel):
    sex: str | None = Field(default=None, pattern="^[MFmf]$")
    birth_date: date | None = None
    height_cm: float | None = Field(default=None, ge=80, le=250)
    weight_kg: float | None = Field(default=None, ge=25, le=350)
    activity_level: str | None = Field(
        default=None, pattern="^(sedentary|light|moderate|very|extra)$"
    )
    goal: str | None = Field(default=None, pattern="^(maintain|lose|gain)$")
    goal_rate_kcal: int | None = Field(default=None, ge=-1500, le=1500)


class MetActivityOut(BaseModel):
    slug: str
    label: str
    met: float
    intensity: str


# ─── Barcode (Open Food Facts) ─────────────────────────────────────


class BarcodeProductOut(BaseModel):
    """A product resolved from a scanned barcode (Open Food Facts)."""

    barcode: str
    name: str
    brand: str | None = None
    quantity: str | None = None       # as printed on the pack, e.g. "500 g"
    kcal_per_100g: int | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    nutriscore: str | None = None     # a..e
    image_url: str | None = None
    # True if it came from our local catalog cache (instant/offline),
    # False if freshly fetched from Open Food Facts.
    from_cache: bool = False


class BarcodeLogIn(BaseModel):
    barcode: str = Field(..., min_length=6, max_length=14)
    portion_g: int = Field(..., ge=1, le=2000)
    meal_type: str | None = Field(
        default=None, description="colazione|spuntino|pranzo|cena; inferred if omitted"
    )
    logged_at: datetime | None = None


# ─── "Cosa cucino?" — piatti dalla spesa ───────────────────────────


class DishIngredientOut(BaseModel):
    name: str
    portion_g: int | None = None
    kcal: int | None = None
    have: bool = False
    status: str | None = None


class DishProposalOut(BaseModel):
    slug: str
    title: str
    covers_category: str | None = None
    kcal_estimate: int | None = None
    ingredients: list[DishIngredientOut] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    note: str | None = None


class RecipeIngredient(BaseModel):
    item: str
    qty: str | None = None


class RecipeDetailOut(BaseModel):
    name: str
    ingredients: list[RecipeIngredient] = Field(default_factory=list)
    steps: str | None = None
    source: str | None = None


class DishShoppingIn(BaseModel):
    names: list[str] = Field(..., min_length=1, max_length=20)


class ExerciseLogIn(BaseModel):
    activity: str = Field(..., min_length=1, max_length=80)
    duration_min: int = Field(..., ge=1, le=600)
    # Provide either a catalog slug (MET looked up) or an explicit met.
    slug: str | None = None
    met: float | None = Field(default=None, ge=0.5, le=20)
    logged_at: datetime | None = None
    notes: str | None = None


class ExerciseLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    logged_at: datetime
    activity: str
    met: float
    duration_min: int
    kcal_burned: int
    notes: str | None


class EnergyBucket(BaseModel):
    label: str
    start: str
    consumed: int
    burned: int
    target: int | None


class EnergyStatsOut(BaseModel):
    period: str
    period_start: date
    period_end: date
    profile_complete: bool
    bmr: int | None
    tdee: int | None
    daily_target: int | None
    days_elapsed: int
    consumed: int
    burned: int
    net: int
    target_total: int | None
    remaining: int | None
    avg_consumed_per_day: int
    avg_burned_per_day: int
    breakdown: list[EnergyBucket]
