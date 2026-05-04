"""Unit tests for `cara.workflows.receipt`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from cara.workflows.base import (
    ExecutionResult,
    ProposedAction,
    StructuredData,
    WorkflowInput,
)
from cara.workflows.receipt import (
    ReceiptWorkflow,
    ReceiptWorkflowConfig,
    infer_category,
    looks_like_receipt,
    parse_date,
    parse_items,
    parse_receipt_text,
    parse_total,
    parse_vendor,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- looks_like_receipt


def test_looks_like_receipt_with_keywords() -> None:
    text = "CONAD\n\nLATTE 1L  1,29\nPANE   2,50\nTOTALE  3,79\n"
    matched, conf = looks_like_receipt(text)
    assert matched is True
    assert conf >= 0.25


def test_looks_like_receipt_short_text_rejected() -> None:
    matched, conf = looks_like_receipt("ciao mondo")
    assert matched is False
    assert conf == 0.0


def test_looks_like_receipt_random_text_low_score() -> None:
    text = "Una poesia di leopardi senza riferimento commerciale " * 4
    matched, conf = looks_like_receipt(text)
    assert matched is False


# ---------------------------------------------------------------- parse_total


def test_parse_total_basic_case() -> None:
    assert parse_total("PANE 2,50\nLATTE 1,29\nTOTALE 3,79") == 379


def test_parse_total_picks_last_total_line() -> None:
    """A receipt with subtotale + totale → last one wins."""
    text = "SUBTOTALE 12,50\nIVA 1,30\nTOTALE 13,80"
    # Subtotale matches `tot.` only loosely; explicit "TOTALE" is the
    # last line and that's what we want.
    assert parse_total(text) == 1380


def test_parse_total_handles_period_decimal() -> None:
    assert parse_total("Totale: 5.99") == 599


def test_parse_total_returns_none_when_missing() -> None:
    assert parse_total("solo testo senza prezzi") is None


# ---------------------------------------------------------------- parse_date


def test_parse_date_dd_mm_yyyy() -> None:
    assert parse_date("Data: 15/03/2026") == date(2026, 3, 15)


def test_parse_date_two_digit_year() -> None:
    assert parse_date("04-05-26") == date(2026, 5, 4)


def test_parse_date_invalid_returns_none() -> None:
    assert parse_date("00/00/0000") is None
    assert parse_date("nessuna data qui") is None


# ---------------------------------------------------------------- parse_vendor


def test_parse_vendor_first_alpha_line() -> None:
    text = "\n\nCONAD - VIA ROMA 5\n00100 ROMA\n\nLATTE 1,29"
    assert parse_vendor(text) == "CONAD - VIA ROMA 5"


def test_parse_vendor_skips_numeric_only_first_line() -> None:
    text = "12345 67890\nESSELUNGA SPA\nLATTE 1,29"
    assert parse_vendor(text) == "ESSELUNGA SPA"


def test_parse_vendor_returns_none_for_garbage() -> None:
    assert parse_vendor("\n\n\n") is None
    assert parse_vendor("") is None


# ---------------------------------------------------------------- parse_items


def test_parse_items_extracts_line_amounts() -> None:
    text = (
        "PANE INTEGRALE  1,80\n"
        "LATTE 1L  1,29\n"
        "TOTALE  3,09\n"
    )
    items = parse_items(text)
    names = [i.name for i in items]
    assert any("PANE" in n for n in names)
    assert any("LATTE" in n for n in names)
    # "TOTALE" must NOT appear as an item.
    assert not any("TOTALE" in n.upper() for n in names)


def test_parse_items_amount_cents_correct() -> None:
    items = parse_items("MELE GOLDEN 3,50\n")
    assert items[0].amount_cents == 350


def test_parse_items_skips_lines_without_amount() -> None:
    text = "INTESTAZIONE NEGOZIO\nPANE 1,80\n00100 ROMA\nMELE 0,99"
    items = parse_items(text)
    names = [i.name for i in items]
    assert any("PANE" in n for n in names)
    assert any("MELE" in n for n in names)
    assert not any("INTESTAZIONE" in n for n in names)


def test_parse_items_skips_runaway_amounts() -> None:
    """An item line with > €2000 is almost always an OCR error."""
    items = parse_items("PANE 2,50\nERRORE OCR 9999,99\nMELE 0,99")
    amounts = [i.amount_cents for i in items]
    assert 250 in amounts
    assert 99 in amounts
    assert 999999 not in amounts


# ---------------------------------------------------------------- infer_category


def test_infer_category_groceries_for_supermarket_chains() -> None:
    from cara.workflows.receipt import ReceiptItem

    cat = infer_category("CONAD - VIA ROMA", [ReceiptItem("LATTE", 129)])
    assert cat == "groceries"


def test_infer_category_health_for_pharmacy() -> None:
    from cara.workflows.receipt import ReceiptItem

    cat = infer_category("FARMACIA SAN MARCO", [ReceiptItem("ASPIRINA", 500)])
    assert cat == "health"


def test_infer_category_transport_for_fuel() -> None:
    from cara.workflows.receipt import ReceiptItem

    cat = infer_category("ENI STATION", [ReceiptItem("DIESEL", 6000)])
    assert cat == "transport"


def test_infer_category_defaults_to_groceries() -> None:
    from cara.workflows.receipt import ReceiptItem

    cat = infer_category("Negozio Sconosciuto", [ReceiptItem("X", 100)])
    assert cat == "groceries"


# ---------------------------------------------------------------- parse_receipt_text


def test_parse_receipt_text_full_round_trip() -> None:
    text = (
        "ESSELUNGA\n"
        "DATA: 04/05/2026\n"
        "PANE INTEGRALE  1,80\n"
        "LATTE 1L  1,29\n"
        "MELE GOLDEN  2,50\n"
        "TOTALE  5,59\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.vendor and "ESSELUNGA" in parsed.vendor
    assert parsed.date == date(2026, 5, 4)
    assert parsed.total_cents == 559
    assert len(parsed.items) >= 3
    assert parsed.confidence > 0.0


# ---------------------------------------------------------------- workflow classify


@dataclass
class _FakeOCRResult:
    text: str = ""


async def test_classify_with_inline_ocr_text_skips_ocr_call() -> None:
    """When `ocr_text` is in payload, the workflow doesn't need to call OCR."""
    wf = ReceiptWorkflow()
    inp = WorkflowInput(
        kind="image",
        payload={"ocr_text": "CONAD\nPANE 1,80\nTOTALE 1,80"},
    )
    res = await wf.classify(inp)
    assert res.matches is True
    assert "ocr_text" in res.hints


async def test_classify_without_ocr_input_returns_no_match() -> None:
    wf = ReceiptWorkflow()
    inp = WorkflowInput(kind="image", payload={})
    res = await wf.classify(inp)
    assert res.matches is False
    assert res.reason.startswith("no_input")


async def test_classify_runs_ocr_and_caches_text() -> None:
    """Without inline text, the workflow calls the OCR adapter and
    caches its output for the extract stage."""
    captured: list[bytes] = []

    async def fake_ocr(data: bytes):
        captured.append(data)
        return _FakeOCRResult(text="CONAD\nPANE 1,80\nTOTALE 1,80")

    wf = ReceiptWorkflow(ocr_extract=fake_ocr)
    inp = WorkflowInput(kind="image", payload={"image_bytes": b"FAKE_PNG"})
    res = await wf.classify(inp)
    assert res.matches is True
    assert captured == [b"FAKE_PNG"]
    assert "ocr_text" in res.hints


async def test_classify_ocr_failure_returns_no_match() -> None:
    async def fake_ocr(data: bytes):  # noqa: ARG001
        raise RuntimeError("ocr broken")

    wf = ReceiptWorkflow(ocr_extract=fake_ocr)
    inp = WorkflowInput(kind="image", payload={"image_bytes": b"X"})
    res = await wf.classify(inp)
    assert res.matches is False
    assert "ocr_error" in res.reason


# ---------------------------------------------------------------- workflow extract


async def test_extract_returns_structured_data() -> None:
    wf = ReceiptWorkflow()
    inp = WorkflowInput(kind="image", payload={"ocr_text": ""})
    text = "CONAD\n04/05/2026\nPANE 1,80\nLATTE 1,29\nTOTALE 3,09"
    data = await wf.extract(inp, hints={"ocr_text": text})
    assert isinstance(data, StructuredData)
    assert data.kind == "receipt"
    assert data.data["vendor"] and "CONAD" in data.data["vendor"]
    assert data.data["total_cents"] == 309
    assert data.data["category"] == "groceries"
    assert len(data.data["items"]) >= 2


# ---------------------------------------------------------------- workflow propose


@dataclass
class _FakeShoppingItem:
    id: int
    title: str
    bought: bool = False


async def test_propose_emits_shopping_match_and_expense() -> None:
    """Receipt with PANE matches an open shopping item «pane integrale»."""
    open_items = [
        _FakeShoppingItem(id=1, title="pane integrale"),
        _FakeShoppingItem(id=2, title="pomodori"),
    ]

    async def fake_list(user_id: int):  # noqa: ARG001
        return open_items

    wf = ReceiptWorkflow(shopping_list=fake_list)
    data = StructuredData(
        kind="receipt",
        data={
            "user_id": 42,
            "vendor": "CONAD",
            "date": "2026-05-04",
            "items": [{"name": "PANE INTEGRALE", "amount_cents": 180}],
            "total_cents": 180,
            "category": "groceries",
        },
        confidence=0.8,
    )
    actions = await wf.propose(data)
    tools = [a.tool for a in actions]
    assert "complete_shopping_item" in tools
    assert "add_expense" in tools
    # The shopping match should reference the matched item id.
    shopping_action = next(a for a in actions if a.tool == "complete_shopping_item")
    assert shopping_action.args["item_id"] == 1


async def test_propose_below_threshold_skips_shopping_match() -> None:
    """Items that don't fuzzy-match → no shopping action, just expense."""
    open_items = [_FakeShoppingItem(id=1, title="latte intero")]

    async def fake_list(user_id: int):  # noqa: ARG001
        return open_items

    wf = ReceiptWorkflow(shopping_list=fake_list)
    data = StructuredData(
        kind="receipt",
        data={
            "user_id": 1,
            "vendor": "X",
            "items": [{"name": "PANE", "amount_cents": 180}],
            "total_cents": 180,
            "category": "groceries",
        },
    )
    actions = await wf.propose(data)
    tools = [a.tool for a in actions]
    assert "complete_shopping_item" not in tools
    assert "add_expense" in tools


async def test_propose_no_total_skips_expense() -> None:
    wf = ReceiptWorkflow()
    data = StructuredData(
        kind="receipt",
        data={
            "user_id": 1, "items": [], "total_cents": None, "category": "groceries",
        },
    )
    actions = await wf.propose(data)
    assert all(a.tool != "add_expense" for a in actions)


async def test_propose_swallows_shopping_list_failure() -> None:
    """If shopping_list adapter raises, the workflow still produces an expense."""
    async def fake_list(user_id: int):  # noqa: ARG001
        raise RuntimeError("db down")

    wf = ReceiptWorkflow(shopping_list=fake_list)
    data = StructuredData(
        kind="receipt",
        data={
            "user_id": 1,
            "items": [{"name": "PANE", "amount_cents": 180}],
            "total_cents": 180,
            "category": "groceries",
            "vendor": "X",
        },
    )
    actions = await wf.propose(data)
    # add_expense survives even if shopping fetch failed.
    assert any(a.tool == "add_expense" for a in actions)


# ---------------------------------------------------------------- workflow execute


@dataclass
class _FakeExpense:
    id: int = 99


async def test_execute_runs_each_action() -> None:
    seen: list[tuple[str, dict]] = []

    async def fake_mark_bought(user_id: int, item_id: int):
        seen.append(("shopping", {"user_id": user_id, "item_id": item_id}))
        return True

    async def fake_add_expense(**kwargs):
        seen.append(("expense", kwargs))
        return _FakeExpense(id=7)

    wf = ReceiptWorkflow(
        shopping_mark_bought=fake_mark_bought,
        add_expense=fake_add_expense,
    )
    actions = [
        ProposedAction(
            tool="complete_shopping_item",
            args={"user_id": 1, "item_id": 5, "matched_name": "pane"},
            summary="x",
        ),
        ProposedAction(
            tool="add_expense",
            args={
                "user_id": 1, "amount_cents": 180, "category": "groceries",
                "vendor": "X", "spent_on": "2026-05-04",
            },
            summary="x",
        ),
    ]
    results = await wf.execute(actions)
    assert all(r.ok for r in results)
    assert results[1].output["expense_id"] == 7


async def test_execute_unknown_tool_marks_failure() -> None:
    wf = ReceiptWorkflow()
    actions = [ProposedAction(tool="banana", args={}, summary="x")]
    results = await wf.execute(actions)
    assert results[0].ok is False
    assert "unknown tool" in (results[0].error or "")


async def test_execute_missing_adapter_marks_failure() -> None:
    """If the workflow was built without adapters, execute logs failure
    instead of crashing."""
    wf = ReceiptWorkflow()
    actions = [
        ProposedAction(
            tool="add_expense",
            args={"amount_cents": 100, "category": "x", "vendor": "y"},
            summary="x",
        ),
    ]
    results = await wf.execute(actions)
    assert results[0].ok is False
    assert "adapter not configured" in (results[0].error or "")


async def test_execute_action_exception_does_not_break_loop() -> None:
    """One failing action shouldn't abort the rest of the batch."""
    async def fake_mark_bought(user_id: int, item_id: int):  # noqa: ARG001
        raise RuntimeError("transient error")

    async def fake_add_expense(**kwargs):  # noqa: ARG001
        return _FakeExpense()

    wf = ReceiptWorkflow(
        shopping_mark_bought=fake_mark_bought,
        add_expense=fake_add_expense,
    )
    actions = [
        ProposedAction(
            tool="complete_shopping_item",
            args={"user_id": 1, "item_id": 5},
            summary="x",
        ),
        ProposedAction(
            tool="add_expense",
            args={"amount_cents": 100, "category": "groceries", "vendor": "y"},
            summary="x",
        ),
    ]
    results = await wf.execute(actions)
    assert results[0].ok is False
    assert results[1].ok is True
