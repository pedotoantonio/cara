"""Unit tests for the diet module's pure logic (no DB / no LLM).

Covers the parts that decide "what counts": portion resolution,
frequency adherence scoring, category state, the lexical meal-parser
fallback, the catalog integrity, and the JSON extractor.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cara.ai import diet_parser
from cara.diet import catalog
from cara.services import diet as diet_svc


# ─── Catalog integrity (faithful to the PDFs) ──────────────────────


def test_catalog_no_duplicate_names() -> None:
    names = [i["name"] for i in catalog.FOOD_ITEMS]
    assert len(names) == len(set(names))


def test_catalog_valid_enums() -> None:
    valid_pc = (None, "legumi", "pesce", "carne", "uova", "formaggio")
    for i in catalog.FOOD_ITEMS:
        assert i["status"] in ("consigliato", "da_moderare", "sconsigliato")
        assert i["protein_category"] in valid_pc


def test_protein_portions_present() -> None:
    # Every protein food carries primo+secondo portions (or category default).
    for i in catalog.FOOD_ITEMS:
        if i["protein_category"] and i["status"] != "sconsigliato":
            assert i["portion_primo_g"] or i["default_portion_g"]
            assert i["portion_secondo_g"] or i["default_portion_g"]


def test_rules_have_five_protein_categories() -> None:
    cats = {r["category"] for r in catalog.DIET_RULES}
    assert {"legumi", "pesce", "carne", "uova", "formaggio"} <= cats
    # context rules transcribed
    assert {"pizza_piadina", "dolce", "aperitivo", "patate_polenta"} <= cats


def test_pancake_recipe_seeded() -> None:
    pancake = next(r for r in catalog.RECIPES if r["name"] == "Pancake")
    assert any("35g" in str(ing.get("qty", "")) for ing in pancake["ingredients"])


# ─── Frequency adherence + state ───────────────────────────────────


@dataclass
class _Rule:
    target_min: float | None
    target_max: float | None


def test_category_state_transitions() -> None:
    rule = _Rule(3, 4)
    assert diet_svc.category_state(0, rule) == "under"
    assert diet_svc.category_state(2, rule) == "under"
    assert diet_svc.category_state(3, rule) == "ok"
    assert diet_svc.category_state(4, rule) == "warn"   # at max
    assert diet_svc.category_state(5, rule) == "over"


def test_formaggio_warn_at_two() -> None:
    rule = _Rule(0, 2)  # formaggio: max 2, no min
    assert diet_svc.category_state(1, rule) == "ok"
    assert diet_svc.category_state(2, rule) == "warn"
    assert diet_svc.category_state(3, rule) == "over"


def test_adherence_perfect_vs_empty() -> None:
    rules = {c: _Rule(3, 4) for c in ("legumi", "pesce", "carne")}
    rules["uova"] = _Rule(1, 2)
    rules["formaggio"] = _Rule(0, 2)
    perfect = {"legumi": 3, "pesce": 3, "carne": 3, "uova": 1, "formaggio": 1}
    empty = {c: 0 for c in perfect}
    assert diet_svc.adherence_score(perfect, rules) == 100.0
    assert diet_svc.adherence_score(empty, rules) < 50.0


def test_overshoot_penalised() -> None:
    rules = {"pesce": _Rule(3, 4)}
    # consuming 8 when max is 4 → score well below 1
    only_pesce = diet_svc.category_score(8, rules["pesce"])
    assert only_pesce < 0.5


def test_week_bounds_monday_to_sunday() -> None:
    from datetime import date

    # 2026-06-03 is a Wednesday.
    start, end = diet_svc.week_bounds(date(2026, 6, 3))
    assert start.weekday() == 0  # Monday
    assert end.weekday() == 6    # Sunday
    assert (end - start).days == 6


# ─── Lexical parser fallback ───────────────────────────────────────


def test_lexical_fallback_matches_catalog_and_grams() -> None:
    names = [i["name"] for i in catalog.FOOD_ITEMS]
    out = diet_parser.lexical_fallback("merluzzo 250g con zucchine e pane integrale", names)
    foods = {i["food"] for i in out["items"]}
    assert "merluzzo" in foods
    assert out["vegetable_present"] is True
    assert out["carb_present"] is True  # pane
    merluzzo = next(i for i in out["items"] if i["food"] == "merluzzo")
    assert merluzzo["portion_g"] == 250


def test_lexical_fallback_longest_match_wins() -> None:
    names = [i["name"] for i in catalog.FOOD_ITEMS]
    out = diet_parser.lexical_fallback("salmone selvaggio alla griglia", names)
    foods = {i["food"] for i in out["items"]}
    assert "salmone selvaggio" in foods


# ─── JSON extraction from messy LLM output ─────────────────────────


def test_extract_json_strips_fences_and_prose() -> None:
    raw = 'Ecco il risultato:\n```json\n{"items": [], "carb_present": true}\n```'
    parsed = diet_parser._extract_json(raw)
    assert parsed == {"items": [], "carb_present": True}


def test_extract_json_returns_none_on_garbage() -> None:
    assert diet_parser._extract_json("nessun json qui") is None


def test_normalise_drops_invalid_categories() -> None:
    raw = {
        "items": [
            {"food": "Tonno", "portion_g": "250", "protein_category": "fish", "status": "ok"},
            {"food": "", "portion_g": None},
        ],
        "carb_present": "yes",
    }
    norm = diet_parser._normalise(raw)
    assert len(norm["items"]) == 1
    item = norm["items"][0]
    assert item["food"] == "tonno"
    assert item["portion_g"] == 250
    assert item["protein_category"] is None  # "fish" rejected
    assert item["status"] is None  # "ok" rejected


# ─── Context flag detection ────────────────────────────────────────


def test_detect_context_flags() -> None:
    flags = diet_svc.detect_context_flags("stasera pizza margherita")
    assert flags.get("pizza_piadina") is True
    assert diet_svc.detect_context_flags("solo pasta al pomodoro") == {}


# ─── Fuzzy match fixes the "ciliege"/"mela" misses ─────────────────


def _fake_catalog():
    """Build {name: FoodItem-like} from the catalog for _match_food."""
    class _F:
        def __init__(self, d):
            self.name = d["name"]
            self.protein_category = d["protein_category"]
            self.food_group = d.get("food_group")
            self.status = d["status"]
            self.default_portion_g = d["default_portion_g"]
            self.portion_primo_g = d["portion_primo_g"]
            self.portion_secondo_g = d["portion_secondo_g"]
    return {i["name"]: _F(i) for i in catalog.FOOD_ITEMS}


def test_fuzzy_match_typo_ciliegie() -> None:
    cat = _fake_catalog()
    # The exact bug the user hit: "ciliege" (typo) must resolve to "ciliegie".
    m = diet_svc._match_food("ciliege", cat)
    assert m is not None and m.name == "ciliegie"
    assert m.food_group == "frutta"


def test_fuzzy_match_singular_mela() -> None:
    cat = _fake_catalog()
    m = diet_svc._match_food("mela", cat)
    assert m is not None and m.name == "mele"


def test_fuzzy_match_rejects_unrelated() -> None:
    cat = _fake_catalog()
    # "caffè" is not a food item (tracked separately) → no spurious match.
    assert diet_svc._match_food("caffè", cat) is None


def test_fruit_items_have_group() -> None:
    fruits = [i for i in catalog.FOOD_ITEMS if i["food_group"] == "frutta"]
    assert "ciliegie" in {f["name"] for f in fruits}
    assert all(i["food_group"] for i in catalog.FOOD_ITEMS)  # everything classified
