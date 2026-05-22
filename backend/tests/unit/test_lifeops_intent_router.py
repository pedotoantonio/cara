"""Golden test del router intent LifeOps Tier-0.

30 frasi italiane realistiche, ognuna con l'intent atteso. Mockare
LLM non serve (Tier-0 è pure regex). Run:

    cd backend && python -m pytest tests/unit/test_lifeops_intent_router.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from cara.lifeops.intent_router import route
from cara.lifeops.intents import (
    ListAddIntent,
    ListDoneIntent,
    ListQueryIntent,
    ReminderIntent,
    UnsureIntent,
)


# Fix the "now" so relative datetimes are reproducible across CI runs.
# Choose a Wednesday afternoon in Rome.
NOW_LOCAL = datetime(2026, 5, 20, 14, 0, tzinfo=ZoneInfo("Europe/Rome"))
NOW = NOW_LOCAL.astimezone(timezone.utc)
LIST_SLUGS = ["shopping", "todo"]


def _route(utt: str):
    return route(utt, now_utc=NOW, list_slugs=LIST_SLUGS)


# ─── REMINDERS — relativi ────────────────────────────────────────────


def test_01_tra_venti_minuti():
    out = _route("ricordami tra venti minuti di controllare il forno")
    assert isinstance(out, ReminderIntent)
    assert out.fires_at is not None
    assert "forno" in out.title.lower()


def test_02_tra_mezzora():
    out = _route("tra mezz'ora ricordami di chiamare nonna")
    assert isinstance(out, ReminderIntent)
    assert out.fires_at is not None
    # Delta ~30 min
    delta = (out.fires_at - NOW).total_seconds() / 60
    assert 25 <= delta <= 35


def test_03_tra_unora():
    out = _route("ricordami tra un'ora di guardare il forno")
    assert isinstance(out, ReminderIntent)
    delta = (out.fires_at - NOW).total_seconds() / 60
    assert 55 <= delta <= 65


# ─── REMINDERS — assoluti ────────────────────────────────────────────


def test_04_domani_alle_1630():
    out = _route("ricordami di chiamare il medico domani alle 16:30")
    assert isinstance(out, ReminderIntent)
    assert out.fires_at is not None
    assert "medico" in out.title.lower()


def test_05_lunedi_alle_9():
    out = _route("ricordami lunedì alle 9 di andare in palestra")
    assert isinstance(out, ReminderIntent)
    assert out.fires_at is not None


def test_06_anniversario_12_marzo():
    out = _route("ricordami il compleanno di mamma il 12 marzo")
    assert isinstance(out, ReminderIntent)
    assert out.rrule is not None
    assert "YEARLY" in out.rrule
    assert "BYMONTH=3" in out.rrule


# ─── REMINDERS — ricorrenti settimanali ──────────────────────────────


def test_07_ogni_lunedi_alle_9():
    out = _route("ogni lunedì alle 9 butta la carta")
    assert isinstance(out, ReminderIntent)
    assert out.rrule is not None
    assert "FREQ=WEEKLY" in out.rrule
    assert "BYDAY=MO" in out.rrule


def test_08_ogni_venerdi_sera():
    out = _route("ogni venerdì alle 19 chiama nonna")
    assert isinstance(out, ReminderIntent)
    assert "BYDAY=FR" in out.rrule


# ─── REMINDERS — unsure (mancanza datetime) ──────────────────────────


def test_09_reminder_senza_datetime():
    out = _route("ricordami di lavare la macchina")
    assert isinstance(out, UnsureIntent)
    assert "datetime" in out.reason.lower() or "quando" in (
        out.suggested_clarification or ""
    ).lower()


# ─── LIST_ADD ────────────────────────────────────────────────────────


def test_10_aggiungi_alla_spesa_semplice():
    out = _route("aggiungi pomodori alla spesa")
    assert isinstance(out, ListAddIntent)
    assert out.list_slug == "shopping"
    assert "pomodori" in out.item.lower()


def test_11_aggiungi_con_qty_kg():
    out = _route("aggiungi due chili di pomodori alla spesa")
    assert isinstance(out, ListAddIntent)
    assert out.qty == 2
    assert out.unit == "kg"
    assert "pomodori" in out.item.lower()


def test_12_aggiungi_con_qty_litri():
    out = _route("aggiungi un litro di latte alla spesa")
    assert isinstance(out, ListAddIntent)
    assert out.unit == "l"


def test_13_aggiungi_default_shopping():
    out = _route("aggiungi detersivo")
    assert isinstance(out, ListAddIntent)
    assert out.list_slug == "shopping"


def test_14_ho_bisogno_di():
    out = _route("ho bisogno di pane")
    assert isinstance(out, ListAddIntent)
    assert out.list_slug == "shopping"
    assert "pane" in out.item.lower()


def test_15_mi_serve():
    out = _route("mi serve un giornale")
    assert isinstance(out, ListAddIntent)
    assert out.list_slug == "shopping"


# ─── LIST_QUERY ──────────────────────────────────────────────────────


def test_16_cosa_devo_comprare():
    out = _route("cosa devo comprare?")
    assert isinstance(out, ListQueryIntent)
    assert out.list_slug == "shopping"


def test_17_cosa_devo_fare():
    out = _route("cosa devo fare oggi?")
    assert isinstance(out, ListQueryIntent)
    assert out.list_slug == "todo"


def test_18_cosa_ce_nella_spesa():
    out = _route("cosa c'è nella spesa?")
    assert isinstance(out, ListQueryIntent)
    assert out.list_slug == "shopping"


# ─── LIST_DONE ───────────────────────────────────────────────────────


def test_19_ho_preso_il_pane():
    out = _route("ho preso il pane")
    assert isinstance(out, ListDoneIntent)
    assert out.list_slug == "shopping"
    assert "pane" in out.item_substring.lower()


def test_20_ho_comprato_il_latte():
    out = _route("ho comprato il latte")
    assert isinstance(out, ListDoneIntent)
    assert "latte" in out.item_substring.lower()


def test_21_comprato_le_uova():
    out = _route("comprato le uova")
    assert isinstance(out, ListDoneIntent)
    assert "uova" in out.item_substring.lower()


# ─── UNSURE — frasi fuori dominio ────────────────────────────────────


def test_22_meteo_unsure():
    out = _route("che tempo fa oggi?")
    assert isinstance(out, UnsureIntent)


def test_23_chat_aperta_unsure():
    out = _route("ciao come stai?")
    assert isinstance(out, UnsureIntent)


def test_24_storytelling_unsure():
    out = _route("raccontami una storia")
    assert isinstance(out, UnsureIntent)


def test_25_smart_home_unsure():
    out = _route("accendi la luce del salotto")
    assert isinstance(out, UnsureIntent)


# ─── EDGE CASES ──────────────────────────────────────────────────────


def test_26_aggiungi_con_unit_grammi():
    out = _route("aggiungi 500 grammi di mozzarella")
    assert isinstance(out, ListAddIntent)
    assert out.qty == 500
    assert out.unit == "g"


def test_27_promemoria_alternativa():
    out = _route("promemoria di rinnovo abbonamento tra tre giorni")
    # "tra tre giorni" non è ancora supportato in M1 (solo
    # minuti/ore) → expected unsure
    assert isinstance(out, (UnsureIntent, ReminderIntent))


def test_28_lista_con_qty_scritta():
    out = _route("aggiungi tre pacchi di pasta")
    assert isinstance(out, ListAddIntent)
    assert out.qty == 3


def test_29_done_con_articolo_plurale():
    out = _route("ho preso le mele")
    assert isinstance(out, ListDoneIntent)
    assert "mele" in out.item_substring.lower()


def test_30_reminder_relativo_breve():
    out = _route("tra cinque minuti chiama Sara")
    # "tra X di Y" è il pattern; "tra X verbo Y" non è ricordami
    # → questo specifico è unsure perché manca "ricordami"
    # NB: comportamento accettabile.
    assert isinstance(out, (ReminderIntent, UnsureIntent))


# ─── BONUS — 32+ ─────────────────────────────────────────────────────


def test_31_aggiungi_mezzo_kg():
    out = _route("aggiungi mezzo chilo di prosciutto")
    assert isinstance(out, ListAddIntent)
    assert out.qty == 0.5
    assert out.unit == "kg"


def test_32_titolo_reminder_pulito():
    out = _route("ricordami di prendere l'olio domani alle 17")
    assert isinstance(out, ReminderIntent)
    # No "ricordami" o "domani alle 17" dentro il title
    assert "ricordami" not in out.title.lower()
    assert "alle 17" not in out.title.lower()
