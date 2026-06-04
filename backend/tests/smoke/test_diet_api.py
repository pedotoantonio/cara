"""CARA Nutrizione (diet) API — smoke tests against a live backend.

Exercises the public surface end-to-end: auth gating, meal logging
(LLM or lexical fallback), today/week views, suggestions, catalog,
intake counters, editable rules, weekly report. Assumes the catalog
has been seeded (`python -m cara.diet.seed`); endpoints still return
200 with empty data if not.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.asyncio


async def test_requires_auth(http: httpx.AsyncClient) -> None:
    for path in ("/api/v1/diet/today", "/api/v1/diet/week", "/api/v1/diet/foods"):
        r = await http.get(path)
        assert r.status_code == 401, f"{path}: {r.text}"


async def test_log_meal_and_today(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/diet/log",
        json={"free_text": "insalata con tonno 250g e pane integrale", "meal_type": "cena"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["log"]["meal_type"] == "cena"
    assert isinstance(body["warnings"], list)
    # Missing fruit on a main meal should be flagged deterministically.
    assert any("frutta" in w.lower() for w in body["warnings"])

    today = await auth_client.get("/api/v1/diet/today")
    assert today.status_code == 200, today.text
    tbody = today.json()
    assert {s["meal_type"] for s in tbody["slots"]} == {
        "colazione", "spuntino", "pranzo", "cena",
    }
    cena_slot = next(s for s in tbody["slots"] if s["meal_type"] == "cena")
    assert cena_slot["done"] is True


async def test_week_shape(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/diet/week")
    assert r.status_code == 200, r.text
    body = r.json()
    cats = {c["category"] for c in body["categories"]}
    assert cats == {"legumi", "pesce", "carne", "uova", "formaggio"}
    assert 0 <= body["adherence_score"] <= 100
    # Plan colors present.
    pesce = next(c for c in body["categories"] if c["category"] == "pesce")
    assert pesce["color"].startswith("#")


async def test_suggest(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/diet/suggest?meal=cena")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meal_type"] == "cena"
    assert isinstance(body["suggestions"], list)
    assert body["speak_text"]  # non-empty voice line for Piper


async def test_foods_filter(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/diet/foods?category=pesce&status=consigliato")
    assert r.status_code == 200, r.text
    for f in r.json():
        assert f["protein_category"] == "pesce"
        assert f["status"] == "consigliato"


async def test_water_and_coffee(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/api/v1/diet/water", json={"ml": 500})
    assert r.status_code == 200, r.text
    assert r.json()["water_ml"] >= 500

    r2 = await auth_client.post("/api/v1/diet/coffee", json={"count": 1})
    assert r2.status_code == 200, r2.text
    assert r2.json()["coffee_count"] >= 1


async def test_rules_editable(auth_client: httpx.AsyncClient) -> None:
    rules = await auth_client.get("/api/v1/diet/rules")
    assert rules.status_code == 200, rules.text
    pesce = next((r for r in rules.json() if r["category"] == "pesce"), None)
    if pesce is None:
        pytest.skip("no active plan seeded for this user")
    patched = await auth_client.patch(
        f"/api/v1/diet/rules/{pesce['id']}", json={"target_max": 5}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["target_max"] == 5
    # restore
    await auth_client.patch(
        f"/api/v1/diet/rules/{pesce['id']}", json={"target_max": pesce["target_max"]}
    )


async def test_weekly_report(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/api/v1/diet/report/weekly")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Aderenza" in body["telegram_text"]
    assert "dispositivo medico" in body["telegram_text"].lower()


async def test_profile_roundtrip_and_energy(auth_client: httpx.AsyncClient) -> None:
    # Set a profile → BMR/TDEE/target computed (Mifflin-St Jeor).
    r = await auth_client.put(
        "/api/v1/diet/profile",
        json={
            "sex": "M", "birth_date": "1990-01-01", "height_cm": 180,
            "weight_kg": 80, "activity_level": "moderate", "goal": "maintain",
        },
    )
    assert r.status_code == 200, r.text
    prof = r.json()
    assert prof["complete"] is True
    assert prof["bmr"] and prof["tdee"] and prof["daily_target"]
    assert prof["tdee"] > prof["bmr"]  # activity factor > 1

    # Energy stats for the day reflect the target.
    e = await auth_client.get("/api/v1/diet/energy?period=day")
    assert e.status_code == 200, e.text
    eb = e.json()
    assert eb["profile_complete"] is True
    assert eb["daily_target"] == prof["daily_target"]
    # remaining = target − consumed + burned
    assert eb["remaining"] == eb["target_total"] - eb["consumed"] + eb["burned"]
    assert len(eb["breakdown"]) == 1  # day → 1 bucket


async def test_exercise_log_and_burn(auth_client: httpx.AsyncClient) -> None:
    cat = await auth_client.get("/api/v1/diet/exercise/catalog")
    assert cat.status_code == 200
    assert any(a["slug"] == "corsa" for a in cat.json())

    r = await auth_client.post(
        "/api/v1/diet/exercise",
        json={"activity": "Corsa", "slug": "corsa", "duration_min": 30},
    )
    assert r.status_code == 200, r.text
    ex = r.json()
    assert ex["kcal_burned"] > 0
    ex_id = ex["id"]
    try:
        # The burn shows up in energy stats.
        e = await auth_client.get("/api/v1/diet/energy?period=day")
        assert e.json()["burned"] >= ex["kcal_burned"]
    finally:
        d = await auth_client.delete(f"/api/v1/diet/exercise/{ex_id}")
        assert d.status_code == 204


async def test_energy_periods(auth_client: httpx.AsyncClient) -> None:
    for period, n in (("week", 7), ("month", None), ("year", 12)):
        e = await auth_client.get(f"/api/v1/diet/energy?period={period}")
        assert e.status_code == 200, e.text
        body = e.json()
        assert body["period"] == period
        if n is not None:
            assert len(body["breakdown"]) == n
