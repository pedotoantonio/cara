"""Unit tests for the diet energy formulas (Mifflin-St Jeor, MET, periods)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from cara.services import diet_energy


@dataclass
class _Profile:
    sex: str | None = "M"
    birth_date: date | None = date(1990, 1, 1)
    height_cm: float | None = 180.0
    weight_kg: float | None = 80.0
    activity_level: str = "moderate"
    goal: str = "maintain"
    goal_rate_kcal: int | None = None


def test_age_from_explicit() -> None:
    assert diet_energy.age_from(date(1990, 6, 15), on=date(2026, 6, 3)) == 35
    assert diet_energy.age_from(date(1990, 6, 1), on=date(2026, 6, 3)) == 36
    assert diet_energy.age_from(None) is None


def test_bmr_mifflin_men() -> None:
    p = _Profile(sex="M")
    age = diet_energy.age_from(p.birth_date)
    expected = 10 * 80 + 6.25 * 180 - 5 * age + 5
    assert diet_energy.compute_bmr(p) == expected


def test_bmr_mifflin_women() -> None:
    p = _Profile(sex="F", weight_kg=60, height_cm=165)
    age = diet_energy.age_from(p.birth_date)
    expected = 10 * 60 + 6.25 * 165 - 5 * age - 161
    assert diet_energy.compute_bmr(p) == expected


def test_bmr_incomplete_profile_none() -> None:
    assert diet_energy.compute_bmr(_Profile(weight_kg=None)) is None
    assert diet_energy.compute_bmr(_Profile(sex=None)) is None


def test_tdee_activity_factor() -> None:
    p = _Profile(activity_level="moderate")
    bmr = diet_energy.compute_bmr(p)
    assert diet_energy.compute_tdee(p) == bmr * 1.55
    p.activity_level = "sedentary"
    assert diet_energy.compute_tdee(p) == bmr * 1.2


def test_daily_target_goal_delta() -> None:
    p = _Profile(goal="maintain")
    maintain = diet_energy.daily_target(p)
    p.goal = "lose"
    assert diet_energy.daily_target(p) == maintain - 500
    p.goal = "gain"
    assert diet_energy.daily_target(p) == maintain + 300
    p.goal = "lose"
    p.goal_rate_kcal = -300  # explicit override beats the default
    assert diet_energy.daily_target(p) == maintain - 300


def test_exercise_kcal_met_formula() -> None:
    # 8 MET × 70 kg × 0.5 h = 280 kcal
    assert diet_energy.exercise_kcal(8, 70, 30) == 280
    # default 70 kg when weight unknown
    assert diet_energy.exercise_kcal(10, None, 60) == 700


def test_period_bounds() -> None:
    anchor = date(2026, 6, 3)  # Wednesday
    assert diet_energy.period_bounds("day", anchor) == (anchor, anchor)
    ws, we = diet_energy.period_bounds("week", anchor)
    assert ws.weekday() == 0 and we.weekday() == 6
    ms, me = diet_energy.period_bounds("month", anchor)
    assert ms == date(2026, 6, 1) and me == date(2026, 6, 30)
    ys, ye = diet_energy.period_bounds("year", anchor)
    assert ys == date(2026, 1, 1) and ye == date(2026, 12, 31)


def test_met_catalog_lookup() -> None:
    corsa = diet_energy.met_for_slug("corsa")
    assert corsa and corsa["met"] == 9.8
    assert diet_energy.met_for_slug("inesistente") is None
    # every catalog entry well-formed
    for m in diet_energy.MET_CATALOG:
        assert {"slug", "label", "met", "intensity"} <= m.keys()
        assert m["met"] > 0
