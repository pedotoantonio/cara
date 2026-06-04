"""Suggestion engine — the heart of the diet module.

At meal time (or on voice request) CARA:
  1. computes the frequencies already consumed this week,
  2. finds the under-target protein categories,
  3. proposes 2-3 concrete dishes from the plan that close the gaps,
  4. warns about imminent overshoots (a category at its weekly max),
  5. recalls the relevant contextual rules (primo → no pane, olio a crudo…).

Dish templates are taken from the plan's own examples (PDF menu) — no
dish is invented. The catalog provides the seasonal vegetable + the
recommended protein for the day.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.diet import PROTEIN_CATEGORIES, FoodItem
from cara.services import diet as diet_svc

log = structlog.get_logger(__name__)

# Concrete dishes per category, transcribed from the plan's examples
# ("pasta con tonno", "riso con piselli", "merluzzo al forno con peperoni",
# "zuppetta di lenticchie", "frittata con spinaci"…). {veg} is filled with
# a seasonal vegetable from the catalog.
DISH_TEMPLATES: dict[str, list[str]] = {
    "pesce": [
        "merluzzo al forno con {veg} e pane integrale",
        "tonno con {veg} (secondo) e pane integrale",
        "riso integrale con gamberi e {veg} (primo)",
    ],
    "carne": [
        "petto di pollo alla piastra con {veg} e pane integrale",
        "vitello con {veg} di stagione",
        "riso integrale con straccetti di tacchino e {veg} (primo)",
    ],
    "legumi": [
        "zuppetta di lenticchie con crostini integrali",
        "pasta integrale con fagioli e {veg} (primo)",
        "riso integrale con piselli e {veg} (primo)",
    ],
    "uova": [
        "frittata (2 uova + albume) con {veg} e pane integrale",
        "uova alla coque con {veg} di stagione",
    ],
    "formaggio": [
        "caprese di mozzarella con {veg} (unico secondo, -1 cucchiaino olio)",
        "ricotta con {veg} e pane integrale (unico secondo)",
    ],
}


async def _seasonal_vegetables(session: AsyncSession, month: int, limit: int = 4) -> list[str]:
    rows = (
        await session.execute(
            select(FoodItem).where(
                FoodItem.protein_category.is_(None),
                FoodItem.status == "consigliato",
                # Vegetables carry "verdura di stagione" in their note —
                # precise enough to exclude other 200g items (e.g. latte).
                FoodItem.notes.ilike("%verdura di stagione%"),
            )
        )
    ).scalars().all()
    # In-season first (current month), then anything else as a fallback.
    in_season = [
        r.name for r in rows
        if r.season_months is None or month in (r.season_months or [])
    ]
    return in_season[:limit] or [r.name for r in rows[:limit]]


def _fill(template: str, veg: str) -> str:
    return template.replace("{veg}", veg)


async def suggest(
    session: AsyncSession, *, user_id: int, meal_type: str = "cena"
) -> dict:
    plan = await diet_svc.get_active_plan(session, user_id)
    rules = await diet_svc.get_rules(session, plan.id) if plan else {}
    rollup = await diet_svc.week_rollup(session, user_id, diet_svc.rome_today())
    veggies = await _seasonal_vegetables(session, diet_svc.rome_now().month)
    veg = veggies[0] if veggies else "verdura di stagione"

    # Rank categories by deficit (target_min - consumed), most under first.
    deficits: list[tuple[str, float]] = []
    warnings: list[str] = []
    under: list[str] = []
    for cat in PROTEIN_CATEGORIES:
        rule = rules.get(cat)
        consumed = rollup.consumed.get(cat, 0)
        state = diet_svc.category_state(consumed, rule)
        tmin = (rule.target_min if rule else None) or 0
        tmax = rule.target_max if rule else None
        if state == "over":
            warnings.append(
                f"{cat}: già {int(consumed)} volte questa settimana, oltre il massimo "
                f"({int(tmax) if tmax else '?'}). Oggi evitalo."
            )
        elif state == "warn":
            warnings.append(
                f"{cat}: sei a {int(consumed)}/{int(tmax) if tmax else '?'} — "
                f"con un'altra porzione sfori. Occhio."
            )
        if state == "under" or consumed < tmin:
            deficits.append((cat, tmin - consumed))
            under.append(cat)
    deficits.sort(key=lambda t: t[1], reverse=True)

    # Build 2-3 concrete dishes covering the most-under categories.
    suggestions: list[dict] = []
    used_veg = 0
    for cat, _ in deficits[:3]:
        templates = DISH_TEMPLATES.get(cat, [])
        if not templates:
            continue
        v = veggies[used_veg % len(veggies)] if veggies else veg
        used_veg += 1
        consumed = int(rollup.consumed.get(cat, 0))
        rule = rules.get(cat)
        tmin = int(rule.target_min) if rule and rule.target_min else 0
        tmax = int(rule.target_max) if rule and rule.target_max else 0
        suggestions.append({
            "title": _fill(templates[0], v).capitalize(),
            "covers_category": cat,
            "detail": (
                f"{cat} questa settimana: {consumed}/{tmin}-{tmax}. "
                f"Alternative: " + "; ".join(_fill(t, v) for t in templates[1:2])
            ),
        })

    # If nothing is under-target, offer a balanced default for the meal.
    if not suggestions:
        suggestions.append({
            "title": _fill(DISH_TEMPLATES["pesce"][0], veg).capitalize(),
            "covers_category": None,
            "detail": "Sei in linea con le frequenze: un pasto equilibrato va benissimo.",
        })

    # Contextual reminders (always-relevant rules of the plan).
    context_reminders = [
        "2-3 cucchiaini di olio EVO a crudo a fine cottura.",
        "Verdura di stagione sempre presente (≥200g cotta o ≥100g insalata).",
    ]
    # If a suggestion is a primo, remind no-pane.
    if any("(primo)" in s["title"].lower() for s in suggestions):
        context_reminders.append("Col primo piatto niente pane aggiunto.")
    if rollup.context_counts.get("pizza_piadina", 0) >= 1:
        context_reminders.append("Pizza/piadina già fatta questa settimana (conta come formaggio).")

    # Natural voice line (Piper).
    speak_text = _speak(meal_type, suggestions, rollup, rules)

    return {
        "meal_type": meal_type,
        "suggestions": suggestions,
        "under_target": under,
        "warnings": warnings,
        "context_reminders": context_reminders,
        "speak_text": speak_text,
    }


def _speak(meal_type: str, suggestions: list[dict], rollup, rules: dict) -> str:
    if not suggestions:
        return f"Per {meal_type} va bene un pasto equilibrato, sei in linea col piano."
    top = suggestions[0]
    cat = top["covers_category"]
    intro = f"Per {meal_type} ti consiglio "
    if cat:
        consumed = int(rollup.consumed.get(cat, 0))
        rule = rules.get(cat)
        tmin = int(rule.target_min) if rule and rule.target_min else 0
        tmax = int(rule.target_max) if rule and rule.target_max else 0
        intro += (
            f"del {cat}: questa settimana ne hai mangiato {consumed} volte su "
            f"{tmin}-{tmax}. "
        )
    line = f"Che ne dici di {top['title'].lower()}? "
    return intro + line + "Ricorda i due-tre cucchiaini d'olio a crudo."
