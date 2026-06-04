"""Core business logic for the CARA Nutrizione (diet) module.

The plan reasons by WEEKLY FREQUENCIES of protein categories + raw
portions; calories are secondary. All "what counts" logic (frequency
rollups, adherence, deterministic warnings) lives here — the LLM only
does linguistic extraction in `cara.ai.diet_parser`.

Week = Monday→Sunday, Europe/Rome (the plan is programmed weekly on
Sundays, per the PDF).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai.diet_parser import parse_meal_text
from cara.models.diet import (
    CATEGORY_COLORS,
    MEAL_TYPES,
    PROTEIN_CATEGORIES,
    DailyIntake,
    DietPlan,
    DietRule,
    FoodItem,
    MealLog,
)

log = structlog.get_logger(__name__)

ROME = ZoneInfo("Europe/Rome")

# Context flags detected from free text (regola di contesto del piano).
_CONTEXT_KEYWORDS = {
    "pizza_piadina": ("pizza", "piadina"),
    "dolce": ("dolce", "torta", "gelato", "dessert", "pasticcin"),
    "aperitivo": ("aperitivo", "spritz", "happy hour"),
    "ristorante": ("ristorante", "trattoria", "osteria", "fuori a cena", "fuori a pranzo"),
    "allenamento_serale": ("allenamento", "palestra", "allenarmi", "workout"),
}


# ─── Time helpers ──────────────────────────────────────────────────


def rome_now() -> datetime:
    return datetime.now(ROME)


def rome_today() -> date:
    return rome_now().date()


def week_bounds(day: date) -> tuple[date, date]:
    """Monday→Sunday week containing `day`."""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def infer_meal_type(dt: datetime) -> str:
    h = dt.astimezone(ROME).hour
    if 5 <= h < 10:
        return "colazione"
    if 12 <= h < 15:
        return "pranzo"
    if 18 <= h <= 23:
        return "cena"
    return "spuntino"


def detect_context_flags(text: str) -> dict[str, bool]:
    low = text.lower()
    return {
        flag: any(kw in low for kw in kws)
        for flag, kws in _CONTEXT_KEYWORDS.items()
        if any(kw in low for kw in kws)
    }


# ─── Plan / catalog access ─────────────────────────────────────────


async def get_active_plan(session: AsyncSession, user_id: int) -> DietPlan | None:
    return (
        await session.execute(
            select(DietPlan)
            .where(DietPlan.user_id == user_id, DietPlan.active.is_(True))
            .order_by(DietPlan.created_at.desc())
        )
    ).scalars().first()


async def get_rules(session: AsyncSession, plan_id: int) -> dict[str, DietRule]:
    rows = (
        await session.execute(select(DietRule).where(DietRule.plan_id == plan_id))
    ).scalars().all()
    return {r.category: r for r in rows}


async def get_catalog(session: AsyncSession) -> list[FoodItem]:
    return list((await session.execute(select(FoodItem))).scalars().all())


async def catalog_names(session: AsyncSession) -> list[str]:
    rows = (await session.execute(select(FoodItem.name))).scalars().all()
    return list(rows)


def _vowel_stem(word: str) -> str:
    """Strip one trailing Italian vowel for singular/plural matching."""
    word = word.strip().lower()
    return word[:-1] if word and word[-1] in "aeiou" else word


def _match_food(name: str, catalog: dict[str, FoodItem]) -> FoodItem | None:
    name = name.strip().lower()
    if not name:
        return None
    if name in catalog:
        return catalog[name]
    # Substring both ways: "tonno" → "tonno fresco", "pasta al tonno" → "tonno".
    for key, item in catalog.items():
        if name in key or key in name:
            return item
    # Italian singular/plural: strip a single trailing vowel and compare
    # stems ("mela"→"mel"=="mele"→"mel", "uovo"→"uov"=="uova"). Safe: it
    # never collides distinct foods (pollo→"poll" ≠ polpo→"polp").
    stem = _vowel_stem(name)
    if len(stem) >= 3:
        for key, item in catalog.items():
            if _vowel_stem(key) == stem:
                return item
    # Fuzzy fallback for typos ("ciliege"→"ciliegie"). rapidfuzz is already
    # a dependency. High cutoff so we don't mis-bind distinct foods.
    try:
        from rapidfuzz import fuzz, process  # noqa: PLC0415

        hit = process.extractOne(
            name, list(catalog.keys()), scorer=fuzz.WRatio, score_cutoff=88
        )
        if hit is not None:
            return catalog[hit[0]]
    except Exception:  # noqa: BLE001
        pass
    return None


# ─── Meal logging ──────────────────────────────────────────────────


@dataclass
class GroundedMeal:
    parsed_items: list[dict]
    protein_category: str | None
    est_kcal: int | None
    warnings: list[str]
    carb_present: bool
    vegetable_present: bool
    fruit_present: bool
    context_flags: dict


def _portion_for(
    item: dict, food: FoodItem, rule: DietRule | None, carb_present: bool
) -> int | None:
    """Resolve the gram portion: explicit → primo/secondo by context → default."""
    if item.get("portion_g"):
        return item["portion_g"]
    is_protein = food.protein_category is not None
    if is_protein and carb_present:
        # Inside a primo piatto → "pasta" column portion.
        return (
            food.portion_primo_g
            or (rule.portion_primo_g if rule else None)
            or food.default_portion_g
        )
    if is_protein:
        return (
            food.portion_secondo_g
            or (rule.portion_secondo_g if rule else None)
            or food.default_portion_g
        )
    return food.default_portion_g


def _ground(
    parsed: dict,
    meal_type: str,
    catalog: dict[str, FoodItem],
    rules: dict[str, DietRule],
    context_flags: dict,
) -> GroundedMeal:
    items_out: list[dict] = []
    proteins_seen: list[tuple[str, int]] = []  # (category, portion) for picking dominant
    pane_present = False
    est_kcal = parsed.get("est_kcal")
    kcal_acc = 0
    kcal_known = False
    warnings = list(parsed.get("warnings", []))
    carb_present = parsed.get("carb_present", False)

    for raw in parsed.get("items", []):
        food = _match_food(raw["food"], catalog)
        if food is None:
            # Unknown food — keep it, no enrichment.
            items_out.append({
                "food": raw["food"],
                "portion_g": raw.get("portion_g"),
                "protein_category": raw.get("protein_category"),
                "food_group": None,
                "status": raw.get("status"),
                "known": False,
            })
            continue
        rule = rules.get(food.protein_category) if food.protein_category else None
        portion = _portion_for(raw, food, rule, carb_present)
        if "pane" in food.name:
            pane_present = True
        if food.protein_category:
            proteins_seen.append((food.protein_category, portion or 0))
        if food.kcal_per_100g and portion:
            kcal_acc += round(food.kcal_per_100g * portion / 100)
            kcal_known = True
        items_out.append({
            "food": food.name,
            "portion_g": portion,
            "protein_category": food.protein_category,
            "food_group": food.food_group,
            "status": food.status,
            "known": True,
        })
        # Portion-overflow warning (>20% over the secondo reference).
        ref = food.portion_secondo_g or (rule.portion_secondo_g if rule else None)
        if ref and portion and portion > ref * 1.2:
            warnings.append(
                f"porzione di {food.name} ({portion}g) oltre quella consigliata (~{ref}g)"
            )
        if food.status == "sconsigliato":
            warnings.append(f"{food.name} è sconsigliato dal piano")
        elif food.status == "da_moderare":
            warnings.append(f"{food.name} è da moderare (occasionale)")

    # Dominant protein category = largest-portion protein in the meal.
    protein_category = None
    if proteins_seen:
        protein_category = max(proteins_seen, key=lambda t: t[1])[0]

    # Deterministic rule warnings (primary meals only).
    if meal_type in ("pranzo", "cena"):
        if not parsed.get("vegetable_present"):
            warnings.append("manca la verdura di stagione (≥200g cotta o ≥100g insalata)")
        if not parsed.get("fruit_present"):
            warnings.append("ricordati la frutta a fine pasto")
    if carb_present and pane_present:
        warnings.append("col primo piatto niente pane aggiunto")
    # Cheese must be the only secondo.
    cats = {c for c, _ in proteins_seen}
    if "formaggio" in cats and len(cats) > 1:
        warnings.append("il formaggio va come unico secondo (no carne/pesce/uova) — togli 1 cucchiaino d'olio")
    if context_flags.get("pizza_piadina"):
        warnings.append("pizza/piadina conta come formaggio nella settimana")

    if est_kcal is None and kcal_known:
        est_kcal = kcal_acc

    # Dedup warnings preserving order.
    seen: set[str] = set()
    deduped = [w for w in warnings if not (w in seen or seen.add(w))]

    return GroundedMeal(
        parsed_items=items_out,
        protein_category=protein_category,
        est_kcal=est_kcal,
        warnings=deduped,
        carb_present=carb_present,
        vegetable_present=parsed.get("vegetable_present", False),
        fruit_present=parsed.get("fruit_present", False),
        context_flags=context_flags,
    )


async def log_meal(
    session: AsyncSession,
    *,
    user_id: int,
    free_text: str,
    meal_type: str | None = None,
    logged_at: datetime | None = None,
) -> tuple[MealLog, GroundedMeal]:
    logged_at = logged_at or datetime.now(UTC)
    meal_type = meal_type if meal_type in MEAL_TYPES else infer_meal_type(logged_at)

    catalog_list = await get_catalog(session)
    catalog = {f.name: f for f in catalog_list}
    plan = await get_active_plan(session, user_id)
    rules = await get_rules(session, plan.id) if plan else {}

    parsed = await parse_meal_text(free_text, [f.name for f in catalog_list])
    context_flags = detect_context_flags(free_text)
    grounded = _ground(parsed, meal_type, catalog, rules, context_flags)

    row = MealLog(
        user_id=user_id,
        logged_at=logged_at,
        meal_type=meal_type,
        free_text=free_text,
        parsed_items=grounded.parsed_items,
        est_kcal=grounded.est_kcal,
        protein_category=grounded.protein_category,
        context_flags=grounded.context_flags,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    log.info(
        "diet.meal_logged",
        user_id=user_id,
        meal_type=meal_type,
        protein=grounded.protein_category,
        items=len(grounded.parsed_items),
        warnings=len(grounded.warnings),
    )
    return row, grounded


# ─── Barcode (Open Food Facts) logging ─────────────────────────────


async def _upsert_off_food(session: AsyncSession, product) -> FoodItem | None:  # noqa: ANN001
    """Cache an OFF product into food_items by barcode (idempotent).

    Lets a re-scan resolve instantly/offline and makes the product show
    up in the catalog. Marked food_group='altro', status='da_moderare'
    (packaged goods are not part of the dietista plan), provenance noted.
    """
    if product is None or not product.found:
        return None
    existing = (
        await session.execute(
            select(FoodItem).where(FoodItem.barcode == product.barcode)
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Refresh kcal if OFF now has it and we didn't.
        if existing.kcal_per_100g is None and product.kcal_per_100g is not None:
            existing.kcal_per_100g = product.kcal_per_100g
        return existing
    # Avoid name collision with an existing catalog row (name is unique).
    name = product.name.strip().lower()[:120]
    clash = (
        await session.execute(select(FoodItem).where(FoodItem.name == name))
    ).scalar_one_or_none()
    if clash is not None:
        # Attach the barcode to the existing row instead of duplicating.
        if clash.barcode is None:
            clash.barcode = product.barcode
            if clash.brand is None:
                clash.brand = product.brand
        return clash
    row = FoodItem(
        name=name,
        status="da_moderare",
        protein_category=None,
        food_group="altro",
        default_portion_g=None,
        kcal_per_100g=product.kcal_per_100g,
        barcode=product.barcode,
        brand=product.brand,
        notes="prodotto confezionato (Open Food Facts, esterno, indicativo)",
    )
    session.add(row)
    await session.flush()
    return row


async def log_barcode_meal(
    session: AsyncSession,
    *,
    user_id: int,
    product,  # OffProduct  # noqa: ANN001
    portion_g: int,
    meal_type: str | None = None,
    logged_at: datetime | None = None,
) -> MealLog:
    """Log a scanned packaged product as a meal entry.

    kcal is computed deterministically (kcal/100g × portion), not via the
    LLM — barcode data is structured, no parsing needed.
    """
    logged_at = logged_at or datetime.now(UTC)
    meal_type = meal_type if meal_type in MEAL_TYPES else infer_meal_type(logged_at)

    food = await _upsert_off_food(session, product)
    est_kcal = None
    if product.kcal_per_100g is not None:
        est_kcal = round(product.kcal_per_100g * portion_g / 100)

    label = product.name
    if product.brand:
        label = f"{product.name} ({product.brand})"

    row = MealLog(
        user_id=user_id,
        logged_at=logged_at,
        meal_type=meal_type,
        free_text=f"[barcode {product.barcode}] {label} {portion_g}g",
        parsed_items=[{
            "food": food.name if food else product.name.lower(),
            "portion_g": portion_g,
            "protein_category": None,
            "food_group": "altro",
            "status": "da_moderare",
            "known": food is not None,
            "barcode": product.barcode,
            "brand": product.brand,
        }],
        est_kcal=est_kcal,
        protein_category=None,
        context_flags={},
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    log.info("diet.barcode_logged", user_id=user_id, barcode=product.barcode,
             portion_g=portion_g, est_kcal=est_kcal)
    return row


# ─── Today ─────────────────────────────────────────────────────────


async def meals_on_day(session: AsyncSession, user_id: int, day: date) -> list[MealLog]:
    start = datetime.combine(day, time.min, tzinfo=ROME).astimezone(UTC)
    end = datetime.combine(day, time.max, tzinfo=ROME).astimezone(UTC)
    return list(
        (
            await session.execute(
                select(MealLog)
                .where(
                    MealLog.user_id == user_id,
                    MealLog.logged_at >= start,
                    MealLog.logged_at <= end,
                )
                .order_by(MealLog.logged_at)
            )
        ).scalars().all()
    )


async def get_intake(session: AsyncSession, user_id: int, day: date) -> DailyIntake:
    row = (
        await session.execute(
            select(DailyIntake).where(
                DailyIntake.user_id == user_id, DailyIntake.day == day
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DailyIntake(user_id=user_id, day=day, water_ml=0, coffee_count=0)
        session.add(row)
        await session.flush()
    return row


async def add_water(session: AsyncSession, user_id: int, ml: int) -> DailyIntake:
    row = await get_intake(session, user_id, rome_today())
    row.water_ml = max(0, row.water_ml + ml)
    await session.commit()
    await session.refresh(row)
    return row


async def add_coffee(session: AsyncSession, user_id: int, count: int) -> DailyIntake:
    row = await get_intake(session, user_id, rome_today())
    row.coffee_count = max(0, row.coffee_count + count)
    await session.commit()
    await session.refresh(row)
    return row


# ─── Week rollup + adherence ───────────────────────────────────────


@dataclass
class WeekRollup:
    week_start: date
    week_end: date
    consumed: dict[str, float]          # category → count
    context_counts: dict[str, int]      # pizza_piadina/dolce/aperitivo
    avg_kcal_per_day: int | None
    avg_water_ml: int | None
    avg_coffee: float | None
    days_logged: int


async def week_rollup(session: AsyncSession, user_id: int, anchor: date) -> WeekRollup:
    start, end = week_bounds(anchor)
    start_dt = datetime.combine(start, time.min, tzinfo=ROME).astimezone(UTC)
    end_dt = datetime.combine(end, time.max, tzinfo=ROME).astimezone(UTC)
    logs = list(
        (
            await session.execute(
                select(MealLog).where(
                    MealLog.user_id == user_id,
                    MealLog.logged_at >= start_dt,
                    MealLog.logged_at <= end_dt,
                )
            )
        ).scalars().all()
    )
    consumed: dict[str, float] = {c: 0.0 for c in PROTEIN_CATEGORIES}
    context_counts: dict[str, int] = {"pizza_piadina": 0, "dolce": 0, "aperitivo": 0}
    kcal_sum = 0
    kcal_days: set[date] = set()
    days_logged: set[date] = set()
    for lg in logs:
        local_day = lg.logged_at.astimezone(ROME).date()
        days_logged.add(local_day)
        # Frequencies count main meals (pranzo/cena).
        if lg.meal_type in ("pranzo", "cena") and lg.protein_category in consumed:
            consumed[lg.protein_category] += 1
        flags = lg.context_flags or {}
        if flags.get("pizza_piadina"):
            context_counts["pizza_piadina"] += 1
            consumed["formaggio"] += 1  # pizza counts as a cheese
        if flags.get("dolce"):
            context_counts["dolce"] += 1
        if flags.get("aperitivo"):
            context_counts["aperitivo"] += 1
        if lg.est_kcal:
            kcal_sum += lg.est_kcal
            kcal_days.add(local_day)

    intakes = list(
        (
            await session.execute(
                select(DailyIntake).where(
                    DailyIntake.user_id == user_id,
                    DailyIntake.day >= start,
                    DailyIntake.day <= end,
                )
            )
        ).scalars().all()
    )
    avg_water = (
        round(sum(i.water_ml for i in intakes) / len(intakes)) if intakes else None
    )
    avg_coffee = (
        round(sum(i.coffee_count for i in intakes) / len(intakes), 1) if intakes else None
    )
    avg_kcal = round(kcal_sum / len(kcal_days)) if kcal_days else None

    return WeekRollup(
        week_start=start,
        week_end=end,
        consumed=consumed,
        context_counts=context_counts,
        avg_kcal_per_day=avg_kcal,
        avg_water_ml=avg_water,
        avg_coffee=avg_coffee,
        days_logged=len(days_logged),
    )


def category_state(consumed: float, rule: DietRule | None) -> str:
    """ok | under | over | warn for a protein category vs its rule."""
    if rule is None:
        return "ok"
    tmin, tmax = rule.target_min, rule.target_max
    if tmax is not None and consumed > tmax:
        return "over"
    if tmax is not None and consumed >= tmax:
        return "warn"
    if tmin is not None and consumed < tmin:
        return "under"
    return "ok"


def category_score(consumed: float, rule: DietRule | None) -> float:
    """Per-category adherence in [0,1]."""
    if rule is None:
        return 1.0
    tmin = rule.target_min or 0
    tmax = rule.target_max
    if tmax is not None and consumed > tmax:
        # Overshoot penalty, proportional to how far past max.
        return max(0.0, 1.0 - (consumed - tmax) / max(tmax, 1))
    if consumed < tmin:
        return consumed / tmin if tmin else 1.0
    return 1.0


def adherence_score(consumed: dict[str, float], rules: dict[str, DietRule]) -> float:
    scores = [
        category_score(consumed.get(c, 0), rules.get(c)) for c in PROTEIN_CATEGORIES
    ]
    return round(sum(scores) / len(scores) * 100, 1) if scores else 0.0


def color_for(category: str) -> str:
    return CATEGORY_COLORS.get(category, "#94a3b8")
