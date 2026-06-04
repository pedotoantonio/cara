"""\"Cosa cucino?\" — piatti cucinabili dagli ingredienti in lista spesa.

Partendo dagli `ShoppingItem` dell'utente (cosa ha o sta per comprare),
propone piatti coerenti col piano (frequenze proteiche, verdura di
stagione, status del catalogo), con calorie stimate in modo
DETERMINISTICO (kcal/100g CREA × porzione). Se mancano pochi ingredienti
per un piatto sensato, li marca come "da comprare".

La ricetta (ingredienti + procedimento) viene generata on-demand dal
LLM locale e cachata in `Recipe`; le ricette seed hanno priorità. Il
LLM produce SOLO testo/struttura — le calorie le calcola il backend.

Calorie indicative/secondarie, coerente col resto del modulo dieta.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.diet import PROTEIN_CATEGORIES, FoodItem, Recipe
from cara.models.shopping import ShoppingItem
from cara.services import diet as diet_svc
from cara.services import diet_suggest

log = structlog.get_logger(__name__)

# Porzione di default a crudo quando il catalogo non la specifica (g).
_DEFAULT_PORTION_G = 80

# Parole funzionali italiane da NON tentare di matchare col catalogo
# (altrimenti "con"/"di" matchano per substring "frolli**ni**…" ecc.).
_STOPWORDS = frozenset({
    "con", "di", "del", "della", "dei", "delle", "alla", "allo", "alle",
    "al", "ai", "agli", "la", "le", "lo", "gli", "il", "un", "una", "uno",
    "e", "ed", "in", "su", "per", "da", "a", "o", "od", "che", "di",
    "stagione", "forno", "piastra", "crudo", "cotto", "primo", "secondo",
    "integrale", "integrali", "fresco", "fresca", "magro", "magra",
})
# Quanti ingredienti mancanti tolleriamo per proporre comunque un piatto.
_MAX_MISSING = 2

# LLM budget per la ricetta (context 4092, NPU 1.5B).
_RECIPE_MAX_NEW_TOKENS = 360
_RKLLM_CONTEXT_TOKENS = 4092
_SAFETY = 64


# ─── Tipi ──────────────────────────────────────────────────────────


@dataclass
class DishIngredient:
    name: str
    portion_g: int | None
    kcal: int | None
    have: bool                      # già nella lista spesa (anche da comprare)
    status: str | None = None       # consigliato|da_moderare|sconsigliato


@dataclass
class DishProposal:
    slug: str                       # stabile, per fetch ricetta
    title: str
    covers_category: str | None
    kcal_estimate: int | None       # totale piatto
    ingredients: list[DishIngredient]
    missing: list[str] = field(default_factory=list)   # da comprare
    note: str | None = None


# ─── Helpers ───────────────────────────────────────────────────────


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:80] or "piatto"


def _kcal_for(food: FoodItem | None, portion_g: int | None) -> int | None:
    if food is None or not food.kcal_per_100g or not portion_g:
        return None
    return round(food.kcal_per_100g * portion_g / 100)


def _portion_for(food: FoodItem) -> int:
    return (
        food.default_portion_g
        or food.portion_secondo_g
        or food.portion_primo_g
        or _DEFAULT_PORTION_G
    )


# ─── Proposta piatti ───────────────────────────────────────────────


async def propose_dishes(
    session: AsyncSession,
    *,
    user_id: int,
    meal_type: str = "cena",
    max_dishes: int = 5,
) -> list[DishProposal]:
    """Piatti cucinabili dalla lista spesa, ordinati per copertura gap."""
    # 1) Lista spesa → mappata al catalogo.
    sh_rows = (
        await session.execute(
            select(ShoppingItem).where(ShoppingItem.user_id == user_id)
        )
    ).scalars().all()
    catalog_list = await diet_svc.get_catalog(session)
    catalog = {f.name: f for f in catalog_list}

    have_foods: dict[str, FoodItem] = {}     # catalog name → FoodItem
    have_raw: list[str] = []                  # voci non riconosciute
    for s in sh_rows:
        food = diet_svc._match_food(s.title, catalog)
        if food is not None:
            have_foods[food.name] = food
        else:
            have_raw.append(s.title.strip().lower())

    have_names = set(have_foods.keys()) | set(have_raw)

    # 2) Piatti candidati dai template del piano (frequency-aware).
    plan = await diet_svc.get_active_plan(session, user_id)
    rules = await diet_svc.get_rules(session, plan.id) if plan else {}
    rollup = await diet_svc.week_rollup(session, user_id, diet_svc.rome_today())
    veggies = await diet_suggest._seasonal_vegetables(
        session, diet_svc.rome_now().month
    )

    # Ordina categorie per deficit settimanale (come diet_suggest).
    deficits: list[tuple[str, float]] = []
    for cat in PROTEIN_CATEGORIES:
        rule = rules.get(cat)
        consumed = rollup.consumed.get(cat, 0)
        tmin = (rule.target_min if rule else None) or 0
        if diet_svc.category_state(consumed, rule) == "under" or consumed < tmin:
            deficits.append((cat, tmin - consumed))
    deficits.sort(key=lambda t: t[1], reverse=True)
    # Se nessun deficit, considera tutte le categorie (ordine piano).
    ordered_cats = [c for c, _ in deficits] or list(PROTEIN_CATEGORIES)

    proposals: list[DishProposal] = []
    used_veg = 0
    for cat in ordered_cats:
        templates = diet_suggest.DISH_TEMPLATES.get(cat, [])
        for tpl in templates:
            veg = veggies[used_veg % len(veggies)] if veggies else "verdura di stagione"
            title = diet_suggest._fill(tpl, veg).capitalize()
            dish = _build_dish(title, cat, catalog, have_names)
            if dish is None:
                continue
            if len(dish.missing) <= _MAX_MISSING:
                proposals.append(dish)
        used_veg += 1
        if len(proposals) >= max_dishes * 2:
            break

    # 3) Ordina: meno ingredienti mancanti prima, poi più kcal noto.
    proposals.sort(key=lambda d: (len(d.missing), -(d.kcal_estimate or 0)))
    # Dedup per titolo, taglia a max_dishes.
    seen: set[str] = set()
    out: list[DishProposal] = []
    for d in proposals:
        if d.title in seen:
            continue
        seen.add(d.title)
        out.append(d)
        if len(out) >= max_dishes:
            break
    return out


def _build_dish(
    title: str,
    cat: str | None,
    catalog: dict[str, FoodItem],
    have_names: set[str],
) -> DishProposal | None:
    """Estrae gli ingredienti-chiave dal titolo del template, calcola kcal,
    e stabilisce cosa manca rispetto alla lista spesa."""
    # Ingredienti candidati = parole "piene" del titolo che matchano il
    # catalogo. Salta le stopword (altrimenti "con"/"di" matchano per
    # substring) e richiedi ≥4 lettere per evitare match spuri.
    words = re.findall(r"[a-zàèéìòù]+", title.lower())
    found: dict[str, FoodItem] = {}
    for w in words:
        if len(w) < 4 or w in _STOPWORDS:
            continue
        f = diet_svc._match_food(w, catalog)
        # Difesa extra: il match deve condividere un prefisso col token
        # (scarta i fuzzy troppo larghi tipo "coque"→qualcosa).
        if f is not None and (w[:4] in f.name or f.name[:4] in w or w in f.name):
            found[f.name] = f
    if not found:
        return None

    ingredients: list[DishIngredient] = []
    missing: list[str] = []
    total_kcal = 0
    kcal_known = False
    for name, food in found.items():
        portion = _portion_for(food)
        kcal = _kcal_for(food, portion)
        # "have" se è in lista (per nome catalogo o substring tra le voci grezze).
        have = name in have_names or any(name in h or h in name for h in have_names)
        if kcal is not None:
            total_kcal += kcal
            kcal_known = True
        ingredients.append(DishIngredient(
            name=name, portion_g=portion, kcal=kcal, have=have, status=food.status,
        ))
        if not have:
            missing.append(name)

    return DishProposal(
        slug=_slugify(title),
        title=title,
        covers_category=cat,
        kcal_estimate=total_kcal if kcal_known else None,
        ingredients=ingredients,
        missing=missing,
        note=None,
    )


# ─── Ricetta (LLM on-demand, cache in Recipe) ──────────────────────


_RECIPE_SYSTEM = (
    "Sei uno chef di casa. Scrivi una ricetta italiana SEMPLICE e sana per il "
    "piatto indicato, coerente con una dieta mediterranea (olio EVO a crudo, "
    "verdura di stagione, porzioni misurate). Rispondi SOLO con JSON valido, "
    "nessun altro testo, in questo schema:\n"
    '{"ingredienti": [{"nome": "...", "qta": "..."}], '
    '"passi": ["passo 1", "passo 2", ...], "porzioni": <numero>}\n'
    "Massimo 8 ingredienti e 6 passi. In italiano."
)


def _render_recipe_prompt(title: str) -> str:
    user = f"Piatto: {title}"
    envelope = (
        f"<|im_start|>system\n{_RECIPE_SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n<|im_end|>\n<|im_start|>assistant\n"
    )
    budget = _RKLLM_CONTEXT_TOKENS - _RECIPE_MAX_NEW_TOKENS - _SAFETY - len(envelope)
    if budget > 0 and len(user) > budget:
        user = user[:budget]
    return (
        f"<|im_start|>system\n{_RECIPE_SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


async def get_or_build_recipe(
    session: AsyncSession, *, title: str
) -> Recipe:
    """Ritorna la ricetta per `title`: dal DB se esiste (seed o cache),
    altrimenti la genera col LLM e la cacha. Fallback robusto se il LLM
    non è disponibile (ricetta minima dal titolo)."""
    name = title.strip()[:160]
    existing = (
        await session.execute(select(Recipe).where(Recipe.name.ilike(name)))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    ingredients: list[dict] = []
    steps: str | None = None
    source = "fallback"

    try:
        from cara.ai import get_llm_service
        from cara.ai.llm import LLMUnavailableError  # noqa: F401

        llm = get_llm_service()
        prompt = _render_recipe_prompt(name)
        chunks: list[str] = []
        async for tok in llm.generate(
            prompt, max_new_tokens=_RECIPE_MAX_NEW_TOKENS, temperature=0.3
        ):
            chunks.append(tok.text)
        raw = _extract_json("".join(chunks))
        if raw:
            ings = raw.get("ingredienti") or []
            ingredients = [
                {"item": str(i.get("nome", "")).strip(), "qty": str(i.get("qta", "")).strip()}
                for i in ings
                if isinstance(i, dict) and i.get("nome")
            ][:8]
            passi = raw.get("passi") or []
            steps = "\n".join(
                f"{n}. {str(p).strip()}" for n, p in enumerate(passi[:6], 1) if str(p).strip()
            ) or None
            if ingredients:
                source = "cara-llm"
    except Exception as exc:  # noqa: BLE001 — fallback below
        log.info("diet.recipe.llm_failed", title=name, error=str(exc))

    if not ingredients:
        # Fallback minimale: niente passi inventati, onesto.
        steps = (
            "Ricetta non disponibile offline. Prepara il piatto con gli "
            "ingredienti elencati, olio EVO a crudo e verdura di stagione."
        )
        source = "fallback"

    row = Recipe(name=name, ingredients=ingredients, steps=steps, source=source)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    log.info("diet.recipe.built", title=name, source=source, n_ing=len(ingredients))
    return row


# ─── Aggiunta mancanti alla spesa ──────────────────────────────────


async def add_missing_to_shopping(
    session: AsyncSession, *, user_id: int, names: list[str]
) -> list[ShoppingItem]:
    """Aggiunge gli ingredienti mancanti alla lista spesa (dedup su quelli
    già presenti). Ritorna le righe create."""
    from cara.services import shopping as shopping_svc

    existing = {
        s.title.strip().lower()
        for s in (
            await session.execute(
                select(ShoppingItem).where(ShoppingItem.user_id == user_id)
            )
        ).scalars().all()
    }
    created: list[ShoppingItem] = []
    for raw in names:
        n = raw.strip()
        if not n or n.lower() in existing:
            continue
        item = await shopping_svc.create_item(session, user_id=user_id, title=n)
        created.append(item)
        existing.add(n.lower())
    await session.commit()
    return created
