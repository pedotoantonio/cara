"""Unit tests for `cara.services.quick_calc`."""

from __future__ import annotations

import pytest

from cara.services.quick_calc import try_calc, _safe_eval, _normalise_for_eval


# ---------------------------------------------------------------- arithmetic


@pytest.mark.parametrize("query,expected", [
    ("Quanto fa 6 per 7?",            "42"),
    ("quanto fa 6 per 7",             "42"),
    ("Quanto fa 12 più 35 meno 4?",   "43"),
    ("Quanto fa 100 diviso 4?",       "25"),
    ("12 * 4 + 3",                    "51"),
    ("2 + 2",                         "4"),
    ("Quanto è 7 al quadrato?",       "49"),
    ("Quanto fa 1,5 + 2,5?",          "4"),       # comma decimal → answer integer
    ("Calcola (3 + 4) * 2",           "14"),
])
def test_arithmetic_intercepts(query: str, expected: str) -> None:
    assert try_calc(query) == expected


@pytest.mark.parametrize("query", [
    "ciao come stai",
    "raccontami una storia",
    "che cosa è la fotosintesi",
    "",
    "    ",
])
def test_arithmetic_does_not_match_prose(query: str) -> None:
    # Empty / unrelated → None, NOT a guess.
    assert try_calc(query) is None


def test_division_by_zero_returns_none() -> None:
    # We catch ZeroDivisionError and let the LLM (or user) handle it.
    assert try_calc("Quanto fa 5 diviso 0") is None


def test_safe_eval_rejects_names() -> None:
    with pytest.raises(ValueError):
        _safe_eval("__import__('os').system('echo hacked')")


def test_safe_eval_rejects_calls() -> None:
    with pytest.raises(ValueError):
        _safe_eval("len([1,2,3])")


# ---------------------------------------------------------------- italian normaliser


def test_normalise_words_to_ops() -> None:
    assert "+" in _normalise_for_eval("3 più 5")
    assert "-" in _normalise_for_eval("10 meno 4")
    assert "*" in _normalise_for_eval("3 per 4")
    assert "/" in _normalise_for_eval("12 diviso 3")


def test_normalise_keeps_x_only_between_digits() -> None:
    # "Anni X 5" should NOT become "Anni*5" because X is between space-letter.
    out = _normalise_for_eval("3 x 5 anni")
    assert "3*5" in out


def test_normalise_strips_trailing_punct() -> None:
    assert _normalise_for_eval("3 + 4?").endswith("4")


# ---------------------------------------------------------------- time / date


def test_what_time_is_it() -> None:
    out = try_calc("Che ore sono?")
    assert out is not None
    assert out.startswith("Sono le ")
    # Format HH:MM
    assert ":" in out


def test_what_day_today() -> None:
    out = try_calc("Che giorno è oggi?")
    assert out is not None
    assert out.startswith("Oggi è ")


def test_what_month() -> None:
    out = try_calc("In che mese siamo?")
    assert out is not None
    assert out.startswith("Siamo a ")


def test_what_year() -> None:
    out = try_calc("In che anno siamo?")
    assert out is not None
    assert out.startswith("Siamo nel ")


def test_days_to_christmas() -> None:
    out = try_calc("Quanti giorni mancano a Natale?")
    assert out is not None
    # "Mancano N giorni al prossimo Natale." OR "È oggi" if 25 dic.
    assert "Natale" in out or "natale" in out


def test_days_to_newyear() -> None:
    out = try_calc("Quanti giorni mancano a Capodanno?")
    assert out is not None
    assert "Capodanno" in out or "capodanno" in out
