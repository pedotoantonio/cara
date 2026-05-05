"""Unit tests for the post-May-2026 intent_router rule additions
(capabilities, identity, list_appointments, complete/delete/duplicate task,
mark_shopping_bought, delete_shopping, add_note, delete_note).

The router is pure regex matching, so no DB / fixtures needed.
"""

from __future__ import annotations

import pytest

from cara.services.intent_router import match


@pytest.mark.parametrize("query,kind", [
    # capabilities
    ("Cosa puoi fare?",                          "capabilities"),
    ("cosa sai fare",                            "capabilities"),
    ("Aiuto",                                    "capabilities"),
    ("Quali sono le tue funzionalità?",          "capabilities"),
    ("a cosa servi?",                            "capabilities"),
    # identity
    ("Chi sei?",                                 "identity"),
    ("come ti chiami",                           "identity"),
    ("presentati",                               "identity"),
    # appointments
    ("Elenca tutti gli appuntamenti",            "list_appointments"),
    ("Quali sono i miei appuntamenti?",          "list_appointments"),
    ("Mostrami gli impegni di domani",           "list_appointments"),
    ("Cosa ho in programma?",                    "list_appointments"),
    ("i miei appuntamenti",                      "list_appointments"),
    # tasks list (existing)
    ("Le mie attività",                          "list_tasks"),
    ("le mie task",                              "list_tasks"),
    ("mostrami la lista",                        "list_tasks"),
    # tasks list today
    ("Cosa devo fare oggi?",                     "list_tasks_today"),
    ("Quali sono i miei task di oggi?",          "list_tasks_today"),
    # complete task
    ("Ho fatto chiamare il dentista",            "complete_task"),
    ("ho finito comprare il pane",               "complete_task"),
    ("Completa pulire il garage",                "complete_task"),
    # delete task
    ("Cancella la task pulire il garage",        "delete_task"),
    ("Elimina chiamare il dentista",             "delete_task"),
    # duplicate
    ("Duplica la task chiamare il dentista",     "duplicate_task"),
    ("copia chiamare il dentista",               "duplicate_task"),
    # add task
    ("Ricordami di comprare il pane",            "add_task"),
    ("aggiungi alla mia lista comprare uova",    "add_task"),
    # add shopping (must take precedence over add_task when "alla spesa")
    ("Aggiungi pane alla spesa",                 "add_shopping"),
    ("Metti latte alla lista della spesa",       "add_shopping"),
    # mark shopping bought
    ("Ho comprato il pane",                      "mark_shopping_bought"),
    ("Ho preso il caffè",                        "mark_shopping_bought"),
    ("ho già comprato uova",                     "mark_shopping_bought"),
    # delete shopping
    ("Cancella zucchero dalla spesa",            "delete_shopping"),
    ("Togli pane dalla lista della spesa",       "delete_shopping"),
    # shopping list
    ("Lista della spesa",                        "list_shopping"),
    ("Cosa devo comprare?",                      "list_shopping"),
    ("Mostrami la spesa",                        "list_shopping"),
    # notes
    ("Salvami una nota che devo chiamare la zia", "add_note"),
    ("Scrivimi una nota di prendere il pane",     "add_note"),
    ("Cancella la nota promemoria",              "delete_note"),
    ("Mostrami le note",                         "list_notes"),
    # who is home
    ("Chi è in casa?",                           "who_is_home"),
])
def test_intent_dispatch(query: str, kind: str) -> None:
    routed = match(query)
    assert routed is not None, f"no match for {query!r}"
    assert routed.kind == kind, (
        f"{query!r} → expected {kind}, got {routed.kind}"
    )


@pytest.mark.parametrize("query", [
    "raccontami una barzelletta",
    "ciao",
    "boh",
    "",
    "   ",
    "x" * 250,   # too long
])
def test_no_match_falls_through(query: str) -> None:
    assert match(query) is None


def test_spiegami_routes_to_discover() -> None:
    # "spiegami X" is intentionally routed to discover_article — that's a
    # valid behaviour, not a fallthrough. This test pins the behaviour so
    # nobody removes it accidentally.
    routed = match("spiegami perché il cielo è blu")
    assert routed is not None
    assert routed.kind == "discover_article"


def test_appointment_scope_today() -> None:
    routed = match("Quali sono i miei appuntamenti di oggi?")
    assert routed is not None
    assert routed.kind == "list_appointments"
    assert routed.args.get("scope") == "today"


def test_appointment_scope_tomorrow() -> None:
    routed = match("Mostrami gli impegni di domani")
    assert routed is not None
    assert routed.args.get("scope") == "tomorrow"


def test_appointment_scope_week() -> None:
    routed = match("Elenca gli appuntamenti di questa settimana")
    assert routed is not None
    assert routed.args.get("scope") == "week"


def test_complete_task_extracts_title() -> None:
    routed = match("Ho fatto chiamare il dentista")
    assert routed is not None
    assert routed.args.get("title") == "chiamare il dentista"


def test_delete_shopping_extracts_title_no_dalla() -> None:
    routed = match("Cancella zucchero dalla spesa")
    assert routed is not None
    assert routed.kind == "delete_shopping"
    # "zucchero" is captured; the "dalla spesa" suffix is consumed by the
    # disambiguating tail.
    assert routed.args.get("title") == "zucchero"


def test_add_note_extracts_body() -> None:
    routed = match("Salvami una nota che devo chiamare la zia")
    assert routed is not None
    assert routed.kind == "add_note"
    assert "chiamare la zia" in routed.args.get("body", "")
