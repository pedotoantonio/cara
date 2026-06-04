"""CARA Nutrizione (diet) REST API.

Endpoints:
  POST /diet/log              — log a meal from free Italian text (LLM parse)
  GET  /diet/today            — today's 5 meal slots + water/coffee
  GET  /diet/suggest          — frequency-gap dish suggestions for a meal
  GET  /diet/week             — weekly frequency totals vs target + adherence
  POST /diet/report/weekly    — generate PDF + shareable Telegram message
  GET  /diet/report/{week}.pdf— stream the generated PDF
  GET  /diet/foods            — query the catalog (status/category filters)
  GET  /diet/rules            — the active plan's editable rules
  PATCH /diet/rules/{id}      — edit a rule (no code change on a new visit)
  GET  /diet/recipes          — seeded recipes (pancake)
  POST /diet/water | /coffee  — increment daily counters

DISCLAIMER: reminders/suggestions only, NOT a medical device.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.diet import MEAL_TYPES, DietProfile, DietRule, ExerciseLog, FoodItem, Recipe
from cara.models.user import User
from cara.schemas.diet import (
    BarcodeLogIn,
    BarcodeProductOut,
    CategoryProgress,
    DishProposalOut,
    DishShoppingIn,
    RecipeDetailOut,
    CoffeeIn,
    DietProfileOut,
    DietProfileUpdate,
    DietRuleOut,
    DietRuleUpdate,
    DishSuggestion,
    EnergyStatsOut,
    ExerciseLogIn,
    ExerciseLogOut,
    FoodItemOut,
    IntakeOut,
    MealLogIn,
    MealLogOut,
    MealLogResult,
    MetActivityOut,
    RecipeOut,
    SuggestOut,
    TodayMealSlot,
    TodayOut,
    WaterIn,
    WeekOut,
    WeeklyReportOut,
)
from cara.config import settings
from cara.services import diet as diet_svc
from cara.services import diet_dishes
from cara.services import diet_energy
from cara.services import diet_report
from cara.services import diet_suggest
from cara.services.off_client import get_off_client
from cara.store import get_session

router = APIRouter(prefix="/diet", tags=["diet"])

DISCLAIMER = (
    "Promemoria e suggerimenti, non un dispositivo medico. La fonte è il piano "
    "della Dott.ssa Elena Poletti; per dubbi rivolgersi a lei."
)


# ─── Logging ───────────────────────────────────────────────────────


@router.post("/log", response_model=MealLogResult)
async def log_meal(
    payload: MealLogIn,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> MealLogResult:
    row, grounded = await diet_svc.log_meal(
        session,
        user_id=user.id,
        free_text=payload.free_text,
        meal_type=payload.meal_type,
        logged_at=payload.logged_at,
    )
    return MealLogResult(
        log=MealLogOut.model_validate(row),
        warnings=grounded.warnings,
        carb_present=grounded.carb_present,
        vegetable_present=grounded.vegetable_present,
        fruit_present=grounded.fruit_present,
    )


# ─── Today ─────────────────────────────────────────────────────────


@router.get("/today", response_model=TodayOut)
async def today(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TodayOut:
    day = diet_svc.rome_today()
    meals = await diet_svc.meals_on_day(session, user.id, day)
    by_type: dict[str, list[MealLogOut]] = {m: [] for m in MEAL_TYPES}
    for lg in meals:
        by_type.setdefault(lg.meal_type, []).append(MealLogOut.model_validate(lg))

    slots = [
        TodayMealSlot(meal_type=m, done=bool(by_type.get(m)), logs=by_type.get(m, []))
        for m in MEAL_TYPES
    ]
    missing = [m for m in MEAL_TYPES if not by_type.get(m)]

    intake = await diet_svc.get_intake(session, user.id, day)
    plan = await diet_svc.get_active_plan(session, user.id)
    rules = await diet_svc.get_rules(session, plan.id) if plan else {}
    water_rule = rules.get("acqua")
    coffee_rule = rules.get("caffe")
    fruit_rule = rules.get("frutta")

    fruit_servings = sum(
        1
        for lg in meals
        for it in (lg.parsed_items or [])
        if _is_fruit_item(it)
    )
    await session.commit()
    return TodayOut(
        day=day,
        slots=slots,
        missing=missing,
        water_ml=intake.water_ml,
        water_target_min=int(water_rule.target_min) if water_rule and water_rule.target_min else 1500,
        water_target_max=int(water_rule.target_max) if water_rule and water_rule.target_max else 2000,
        coffee_count=intake.coffee_count,
        coffee_max=int(coffee_rule.target_max) if coffee_rule and coffee_rule.target_max else 3,
        fruit_servings=fruit_servings,
        fruit_target_min=int(fruit_rule.target_min) if fruit_rule and fruit_rule.target_min else 2,
    )


def _is_fruit_item(item: dict) -> bool:
    # Robust: classified as fruit by the catalog (food_group), with a
    # legacy fallback for rows logged before food_group existed.
    if item.get("food_group") == "frutta":
        return True
    return (
        item.get("food_group") is None
        and item.get("known")
        and not item.get("protein_category")
        and item.get("portion_g") in (100, 150, 300)
    )


# ─── Suggest ───────────────────────────────────────────────────────


@router.get("/suggest", response_model=SuggestOut)
async def suggest(
    meal: str = Query("cena"),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SuggestOut:
    if meal not in MEAL_TYPES:
        meal = "cena"
    result = await diet_suggest.suggest(session, user_id=user.id, meal_type=meal)
    return SuggestOut(
        meal_type=result["meal_type"],
        suggestions=[DishSuggestion(**s) for s in result["suggestions"]],
        under_target=result["under_target"],
        warnings=result["warnings"],
        context_reminders=result["context_reminders"],
        speak_text=result["speak_text"],
    )


# ─── "Cosa cucino?" — piatti dalla spesa ───────────────────────────


@router.get("/dishes", response_model=list[DishProposalOut])
async def dishes(
    meal: str = Query("cena"),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DishProposalOut]:
    """Piatti cucinabili dagli ingredienti in lista spesa, con calorie."""
    if meal not in MEAL_TYPES:
        meal = "cena"
    proposals = await diet_dishes.propose_dishes(
        session, user_id=user.id, meal_type=meal
    )
    return [
        DishProposalOut(
            slug=d.slug,
            title=d.title,
            covers_category=d.covers_category,
            kcal_estimate=d.kcal_estimate,
            ingredients=[
                {
                    "name": i.name, "portion_g": i.portion_g, "kcal": i.kcal,
                    "have": i.have, "status": i.status,
                }
                for i in d.ingredients
            ],
            missing=d.missing,
            note=d.note,
        )
        for d in proposals
    ]


@router.get("/dishes/recipe", response_model=RecipeDetailOut)
async def dish_recipe(
    title: str = Query(..., min_length=2, max_length=160),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RecipeDetailOut:
    """Ricetta completa di un piatto (genera + cacha se assente)."""
    recipe = await diet_dishes.get_or_build_recipe(session, title=title)
    return RecipeDetailOut(
        name=recipe.name,
        ingredients=recipe.ingredients or [],
        steps=recipe.steps,
        source=recipe.source,
    )


@router.post("/dishes/shopping", status_code=201)
async def dish_add_to_shopping(
    payload: DishShoppingIn,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, int]:
    """Aggiunge gli ingredienti mancanti di un piatto alla lista spesa."""
    created = await diet_dishes.add_missing_to_shopping(
        session, user_id=user.id, names=payload.names
    )
    # Publish family-bus events for each created item (best-effort).
    try:
        from cara.schemas.shopping import ShoppingItemOut
        from cara.services.family_bus import publish as fb_publish
        for item in created:
            await fb_publish(
                "shopping.created", user_id=user.id,
                payload=ShoppingItemOut.model_validate(item).model_dump(mode="json"),
            )
    except Exception:  # noqa: BLE001 — bus is best-effort
        pass
    return {"added": len(created)}


# ─── Week ──────────────────────────────────────────────────────────


@router.get("/week", response_model=WeekOut)
async def week(
    anchor: date | None = Query(None, description="any day in the target week"),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WeekOut:
    anchor = anchor or diet_svc.rome_today()
    plan = await diet_svc.get_active_plan(session, user.id)
    rules = await diet_svc.get_rules(session, plan.id) if plan else {}
    rollup = await diet_svc.week_rollup(session, user.id, anchor)
    adherence = diet_svc.adherence_score(rollup.consumed, rules)

    categories = []
    for cat in ("legumi", "pesce", "carne", "uova", "formaggio"):
        rule = rules.get(cat)
        consumed = rollup.consumed.get(cat, 0)
        categories.append(CategoryProgress(
            category=cat,
            color=diet_svc.color_for(cat),
            consumed=consumed,
            target_min=rule.target_min if rule else None,
            target_max=rule.target_max if rule else None,
            state=diet_svc.category_state(consumed, rule),
        ))

    notes = []
    for c in categories:
        if c.state == "under":
            notes.append(f"{c.category.capitalize()} sotto target — da recuperare.")
        elif c.state == "over":
            notes.append(f"{c.category.capitalize()} oltre il massimo.")
    return WeekOut(
        week_start=rollup.week_start,
        week_end=rollup.week_end,
        categories=categories,
        adherence_score=adherence,
        avg_kcal_per_day=rollup.avg_kcal_per_day,
        avg_water_ml=rollup.avg_water_ml,
        avg_coffee=rollup.avg_coffee,
        notes=notes,
    )


# ─── Weekly report ─────────────────────────────────────────────────


@router.post("/report/weekly", response_model=WeeklyReportOut)
async def report_weekly(
    anchor: date | None = Query(None),
    share_telegram: bool = Query(False),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WeeklyReportOut:
    report = await diet_report.build_weekly_report(
        session, user_id=user.id, anchor=anchor, send_telegram=share_telegram
    )
    pdf_url = (
        f"/api/v1/diet/report/{report.week_start.isoformat()}.pdf"
        if report.pdf_path
        else None
    )
    return WeeklyReportOut(
        week_start=report.week_start,
        week_end=report.week_end,
        pdf_url=pdf_url,
        telegram_text=report.telegram_text,
        sent_to_telegram=share_telegram,
    )


@router.get("/report/{week_start}.pdf")
async def report_pdf(
    week_start: date,
    user: User = Depends(get_current_user),  # noqa: B008
) -> FileResponse:
    path = diet_report.REPORTS_DIR / f"{user.id}-{week_start.isoformat()}.pdf"
    if not Path(path).is_file():
        raise HTTPException(status_code=404, detail="report non ancora generato")
    return FileResponse(
        str(path), media_type="application/pdf",
        filename=f"cara-dieta-{week_start.isoformat()}.pdf",
    )


# ─── Barcode (Open Food Facts) ─────────────────────────────────────

# Lazy redis client for the OFF product cache (same pattern as diagnostics).
_off_redis = None


def _get_off_client():
    global _off_redis
    if _off_redis is None:
        try:
            import redis.asyncio as aioredis  # noqa: PLC0415

            _off_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        except Exception:  # noqa: BLE001 — cache optional; OFF works without it
            _off_redis = None
    return get_off_client(_off_redis)


def _product_out(p, *, from_cache: bool = False) -> BarcodeProductOut:  # noqa: ANN001
    return BarcodeProductOut(
        barcode=p.barcode,
        name=p.name,
        brand=p.brand,
        quantity=p.quantity,
        kcal_per_100g=p.kcal_per_100g,
        protein_g=p.protein_g,
        carbs_g=p.carbs_g,
        fat_g=p.fat_g,
        fiber_g=p.fiber_g,
        nutriscore=p.nutriscore,
        image_url=p.image_url,
        from_cache=from_cache,
    )


@router.get("/barcode/{code}", response_model=BarcodeProductOut)
async def barcode_lookup(
    code: str,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BarcodeProductOut:
    """Resolve a scanned barcode to a product (local catalog → OFF)."""
    code = code.strip()
    # 1) Local catalog cache (instant, offline).
    cached = (
        await session.execute(select(FoodItem).where(FoodItem.barcode == code))
    ).scalar_one_or_none()
    if cached is not None:
        return BarcodeProductOut(
            barcode=code,
            name=cached.name,
            brand=cached.brand,
            quantity=None,
            kcal_per_100g=cached.kcal_per_100g,
            from_cache=True,
        )
    # 2) Open Food Facts.
    product = await _get_off_client().lookup(code)
    if product is None:
        raise HTTPException(status_code=404, detail="Prodotto non trovato")
    return _product_out(product, from_cache=False)


@router.post("/barcode/log", response_model=MealLogOut)
async def barcode_log(
    payload: BarcodeLogIn,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> MealLogOut:
    """Log a scanned product as a meal (deterministic kcal from portion)."""
    product = await _get_off_client().lookup(payload.barcode)
    if product is None:
        raise HTTPException(status_code=404, detail="Prodotto non trovato")
    row = await diet_svc.log_barcode_meal(
        session,
        user_id=user.id,
        product=product,
        portion_g=payload.portion_g,
        meal_type=payload.meal_type,
        logged_at=payload.logged_at,
    )
    return MealLogOut.model_validate(row)


# ─── Catalog ───────────────────────────────────────────────────────


@router.get("/foods", response_model=list[FoodItemOut])
async def foods(
    status: str | None = Query(None),
    category: str | None = Query(None),
    q: str | None = Query(None, description="name contains"),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[FoodItemOut]:
    stmt = select(FoodItem)
    if status:
        stmt = stmt.where(FoodItem.status == status)
    if category:
        stmt = stmt.where(FoodItem.protein_category == category)
    if q:
        stmt = stmt.where(FoodItem.name.ilike(f"%{q.lower()}%"))
    stmt = stmt.order_by(FoodItem.protein_category.nullslast(), FoodItem.name)
    rows = (await session.execute(stmt)).scalars().all()
    return [FoodItemOut.model_validate(r) for r in rows]


@router.get("/recipes", response_model=list[RecipeOut])
async def recipes(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[RecipeOut]:
    rows = (await session.execute(select(Recipe).order_by(Recipe.name))).scalars().all()
    return [RecipeOut.model_validate(r) for r in rows]


# ─── Rules (editable) ──────────────────────────────────────────────


@router.get("/rules", response_model=list[DietRuleOut])
async def rules(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DietRuleOut]:
    plan = await diet_svc.get_active_plan(session, user.id)
    if plan is None:
        return []
    rows = (
        await session.execute(
            select(DietRule).where(DietRule.plan_id == plan.id).order_by(DietRule.category)
        )
    ).scalars().all()
    return [DietRuleOut.model_validate(r) for r in rows]


@router.patch("/rules/{rule_id}", response_model=DietRuleOut)
async def update_rule(
    rule_id: int,
    payload: DietRuleUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DietRuleOut:
    plan = await diet_svc.get_active_plan(session, user.id)
    row = (
        await session.execute(select(DietRule).where(DietRule.id == rule_id))
    ).scalar_one_or_none()
    if row is None or plan is None or row.plan_id != plan.id:
        raise HTTPException(status_code=404, detail="regola non trovata")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    return DietRuleOut.model_validate(row)


# ─── Intake counters ───────────────────────────────────────────────


@router.post("/water", response_model=IntakeOut)
async def water(
    payload: WaterIn,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> IntakeOut:
    row = await diet_svc.add_water(session, user.id, payload.ml)
    return IntakeOut(day=row.day, water_ml=row.water_ml, coffee_count=row.coffee_count)


@router.post("/coffee", response_model=IntakeOut)
async def coffee(
    payload: CoffeeIn,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> IntakeOut:
    row = await diet_svc.add_coffee(session, user.id, payload.count)
    return IntakeOut(day=row.day, water_ml=row.water_ml, coffee_count=row.coffee_count)


@router.get("/disclaimer")
async def disclaimer() -> dict[str, str]:
    return {"disclaimer": DISCLAIMER}


# ─── Energy: profile ───────────────────────────────────────────────


def _profile_out(p: DietProfile | None) -> DietProfileOut:
    if p is None:
        return DietProfileOut(
            sex=None, birth_date=None, height_cm=None, weight_kg=None,
            activity_level="moderate", goal="maintain", goal_rate_kcal=None,
            age=None, bmr=None, tdee=None, daily_target=None, complete=False,
        )
    tgt = diet_energy.daily_target(p)
    return DietProfileOut(
        sex=p.sex, birth_date=p.birth_date, height_cm=p.height_cm,
        weight_kg=p.weight_kg, activity_level=p.activity_level, goal=p.goal,
        goal_rate_kcal=p.goal_rate_kcal,
        age=diet_energy.age_from(p.birth_date),
        bmr=round(diet_energy.compute_bmr(p)) if diet_energy.compute_bmr(p) else None,
        tdee=round(diet_energy.compute_tdee(p)) if diet_energy.compute_tdee(p) else None,
        daily_target=tgt,
        complete=tgt is not None,
    )


@router.get("/profile", response_model=DietProfileOut)
async def get_profile(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DietProfileOut:
    p = (
        await session.execute(select(DietProfile).where(DietProfile.user_id == user.id))
    ).scalar_one_or_none()
    return _profile_out(p)


@router.put("/profile", response_model=DietProfileOut)
async def put_profile(
    payload: DietProfileUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DietProfileOut:
    p = (
        await session.execute(select(DietProfile).where(DietProfile.user_id == user.id))
    ).scalar_one_or_none()
    if p is None:
        p = DietProfile(user_id=user.id)
        session.add(p)
    data = payload.model_dump(exclude_unset=True)
    if data.get("sex"):
        data["sex"] = data["sex"].upper()
    for field, value in data.items():
        setattr(p, field, value)
    p.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(p)
    return _profile_out(p)


# ─── Energy: stats (real-time, day/week/month/year) ────────────────


@router.get("/energy", response_model=EnergyStatsOut)
async def energy(
    period: str = Query("day"),
    anchor: date | None = Query(None),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> EnergyStatsOut:
    stats = await diet_energy.energy_stats(
        session, user_id=user.id, period=period, anchor=anchor
    )
    return EnergyStatsOut(**stats.__dict__)


# ─── Energy: exercise ──────────────────────────────────────────────


@router.get("/exercise/catalog", response_model=list[MetActivityOut])
async def exercise_catalog(
    user: User = Depends(get_current_user),  # noqa: B008
) -> list[MetActivityOut]:
    return [MetActivityOut(**m) for m in diet_energy.MET_CATALOG]


@router.post("/exercise", response_model=ExerciseLogOut)
async def add_exercise(
    payload: ExerciseLogIn,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ExerciseLogOut:
    met = payload.met
    activity = payload.activity
    if payload.slug:
        m = diet_energy.met_for_slug(payload.slug)
        if m:
            met = m["met"]
            if not activity:
                activity = m["label"]
    if met is None:
        raise HTTPException(status_code=422, detail="met o slug richiesti")
    row = await diet_energy.log_exercise(
        session, user_id=user.id, activity=activity, met=met,
        duration_min=payload.duration_min, logged_at=payload.logged_at,
        notes=payload.notes,
    )
    return ExerciseLogOut.model_validate(row)


@router.get("/exercise", response_model=list[ExerciseLogOut])
async def list_exercise(
    day: date | None = Query(None),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ExerciseLogOut]:
    rows = await diet_energy.exercises_on_day(
        session, user.id, day or diet_svc.rome_today()
    )
    return [ExerciseLogOut.model_validate(r) for r in rows]


@router.delete("/exercise/{exercise_id}", status_code=204)
async def delete_exercise(
    exercise_id: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    row = (
        await session.execute(
            select(ExerciseLog).where(ExerciseLog.id == exercise_id)
        )
    ).scalar_one_or_none()
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="allenamento non trovato")
    await session.delete(row)
    await session.commit()
