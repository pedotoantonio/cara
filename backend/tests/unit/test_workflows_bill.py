"""Unit tests for `cara.workflows.bill`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from cara.workflows.base import (
    ProposedAction,
    StructuredData,
    WorkflowInput,
)
from cara.workflows.bill import (
    BillWorkflow,
    looks_like_bill,
    parse_amount_cents,
    parse_bill_text,
    parse_customer_id,
    parse_due_date,
    parse_provider,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- parsers


def test_looks_like_bill_with_enel_keywords() -> None:
    text = (
        "ENEL ENERGIA S.P.A.\n"
        "Bolletta N. 12345\n"
        "Importo da pagare: € 87,30\n"
        "Scadenza: 15/05/2026\n"
        "Numero cliente: 1234567\n"
    )
    matched, conf = looks_like_bill(text)
    assert matched is True
    assert conf >= 0.4


def test_looks_like_bill_short_text_rejected() -> None:
    matched, conf = looks_like_bill("ciao")
    assert matched is False


def test_looks_like_bill_random_invoice_text() -> None:
    matched, conf = looks_like_bill("solo qualche parola innocua " * 5)
    assert matched is False


def test_parse_amount_cents_importo_form() -> None:
    text = "Importo da pagare: € 87,30 entro il 15/05/2026"
    assert parse_amount_cents(text) == 8730


def test_parse_amount_cents_totale_form() -> None:
    assert parse_amount_cents("Totale da pagare 105,00 EUR") == 10500


def test_parse_amount_cents_fallback() -> None:
    """When no explicit 'importo' keyword, accept a euro-suffixed amount."""
    assert parse_amount_cents("Saldo: € 42,15") == 4215


def test_parse_amount_cents_rejects_implausible_huge() -> None:
    """A 5-digit utility bill is almost always an OCR error."""
    assert parse_amount_cents("Importo da pagare: 99999,99") is None


def test_parse_amount_cents_returns_none_when_missing() -> None:
    assert parse_amount_cents("nessun importo qui") is None


def test_parse_due_date_scadenza_form() -> None:
    assert parse_due_date("Scadenza: 15/05/2026") == date(2026, 5, 15)


def test_parse_due_date_entro_il_form() -> None:
    assert parse_due_date("Pagare entro il 31-12-26") == date(2026, 12, 31)


def test_parse_due_date_returns_none_when_missing() -> None:
    assert parse_due_date("solo testo") is None


def test_parse_provider_known_brand() -> None:
    assert parse_provider("Bolletta Enel del mese di maggio") == "Enel"


def test_parse_provider_telecom_aliases() -> None:
    assert parse_provider("Telecom Italia bolletta...") == "TIM"


def test_parse_provider_returns_none_for_unknown() -> None:
    assert parse_provider("Fornitore Sconosciuto") is None


def test_parse_customer_id_extracts() -> None:
    assert parse_customer_id("Numero cliente: ABC-12345") == "ABC-12345"
    assert parse_customer_id("Codice cliente: 9876543") == "9876543"


def test_parse_customer_id_returns_none_when_missing() -> None:
    assert parse_customer_id("no customer id here") is None


def test_parse_bill_text_full_round_trip() -> None:
    text = (
        "ENEL ENERGIA S.P.A.\n"
        "Bolletta luce - Periodo aprile 2026\n"
        "Importo da pagare: € 87,30\n"
        "Scadenza: 15/05/2026\n"
        "Numero cliente: 1234567\n"
    )
    parsed = parse_bill_text(text)
    assert parsed.provider == "Enel"
    assert parsed.amount_cents == 8730
    assert parsed.due_date == date(2026, 5, 15)
    assert parsed.customer_id == "1234567"
    assert parsed.confidence > 0.4


# ---------------------------------------------------------------- classify


async def test_classify_with_inline_pdf_text_skips_extractor() -> None:
    wf = BillWorkflow()
    text = (
        "ENEL bolletta\n"
        "Importo da pagare 50,00\n"
        "Scadenza 01/06/2026\n"
        "Numero cliente: 12345"
    )
    inp = WorkflowInput(kind="pdf", payload={"pdf_text": text})
    res = await wf.classify(inp)
    assert res.matches is True


async def test_classify_runs_pdf_extractor_when_only_bytes_given() -> None:
    captured: list[bytes] = []

    def fake_pdf(b: bytes) -> str:
        captured.append(b)
        return (
            "Vodafone bolletta\n"
            "Importo da pagare: € 25,00\n"
            "Scadenza: 30/06/2026\n"
            "Codice cliente: VF-9999"
        )

    wf = BillWorkflow(pdf_extract=fake_pdf)
    inp = WorkflowInput(kind="pdf", payload={"pdf_bytes": b"FAKE_PDF"})
    res = await wf.classify(inp)
    assert captured == [b"FAKE_PDF"]
    assert res.matches is True


async def test_classify_pdf_extract_failure_no_match() -> None:
    def fake_pdf(b: bytes) -> str:  # noqa: ARG001
        raise RuntimeError("corrupt pdf")

    wf = BillWorkflow(pdf_extract=fake_pdf)
    inp = WorkflowInput(kind="pdf", payload={"pdf_bytes": b"X"})
    res = await wf.classify(inp)
    assert res.matches is False
    assert "pdf_error" in res.reason


async def test_classify_no_input_no_match() -> None:
    wf = BillWorkflow()
    res = await wf.classify(WorkflowInput(kind="pdf", payload={}))
    assert res.matches is False


# ---------------------------------------------------------------- extract


async def test_extract_returns_structured_data() -> None:
    wf = BillWorkflow()
    text = (
        "ENEL bolletta\n"
        "Importo da pagare: € 87,30\n"
        "Scadenza: 15/05/2026\n"
        "Numero cliente: ABC123"
    )
    inp = WorkflowInput(kind="pdf", payload={"user_id": 42, "pdf_text": text})
    data = await wf.extract(inp, hints={"pdf_text": text})
    assert data.kind == "bill"
    assert data.data["user_id"] == 42
    assert data.data["provider"] == "Enel"
    assert data.data["amount_cents"] == 8730
    assert data.data["due_date"] == "2026-05-15"
    assert data.data["category"] == "utilities"


# ---------------------------------------------------------------- propose


async def test_propose_emits_task_and_pending_expense() -> None:
    wf = BillWorkflow()
    data = StructuredData(
        kind="bill",
        data={
            "user_id": 1, "provider": "Enel",
            "amount_cents": 8730, "due_date": "2026-05-15",
            "category": "utilities",
        },
        confidence=0.8,
    )
    actions = await wf.propose(data)
    tools = [a.tool for a in actions]
    assert "add_task" in tools
    assert "add_expense_pending" in tools


async def test_propose_no_user_id_no_actions() -> None:
    wf = BillWorkflow()
    data = StructuredData(
        kind="bill", data={"user_id": None, "amount_cents": 100},
    )
    assert await wf.propose(data) == []


async def test_propose_no_amount_still_emits_task() -> None:
    """Provider known but amount unparseable → task with placeholder."""
    wf = BillWorkflow()
    data = StructuredData(
        kind="bill",
        data={"user_id": 1, "provider": "TIM", "due_date": "2026-06-01"},
    )
    actions = await wf.propose(data)
    tools = [a.tool for a in actions]
    assert "add_task" in tools
    assert "add_expense_pending" not in tools


# ---------------------------------------------------------------- execute


@dataclass
class _FakeTask:
    id: int = 7


async def test_execute_creates_task() -> None:
    seen: list[dict] = []

    async def fake_add_task(*, user_id, title, due_date):
        seen.append({"user_id": user_id, "title": title, "due_date": due_date})
        return _FakeTask(id=42)

    wf = BillWorkflow(add_task=fake_add_task)
    actions = [
        ProposedAction(
            tool="add_task",
            args={"user_id": 1, "title": "Pagare Enel", "due_date": "2026-05-15"},
            summary="x",
        ),
    ]
    results = await wf.execute(actions)
    assert results[0].ok
    assert seen[0]["due_date"] == date(2026, 5, 15)


async def test_execute_pending_expense_only_marks_pending() -> None:
    """Pending expense returns a structured marker, NOT a real expense write."""
    wf = BillWorkflow()
    actions = [
        ProposedAction(
            tool="add_expense_pending",
            args={
                "user_id": 1, "amount_cents": 8730, "category": "utilities",
                "vendor": "Enel", "due_date": "2026-05-15",
            },
            summary="x",
        ),
    ]
    results = await wf.execute(actions)
    assert results[0].ok
    assert results[0].output["pending"] is True
    assert results[0].output["amount_cents"] == 8730


async def test_execute_unknown_tool_marks_failure() -> None:
    wf = BillWorkflow()
    results = await wf.execute([
        ProposedAction(tool="banana", args={}, summary="x"),
    ])
    assert results[0].ok is False


async def test_execute_no_add_task_adapter_marks_failure() -> None:
    wf = BillWorkflow()
    results = await wf.execute([
        ProposedAction(
            tool="add_task",
            args={"user_id": 1, "title": "x", "due_date": None},
            summary="x",
        ),
    ])
    assert results[0].ok is False
    assert "adapter not configured" in (results[0].error or "")
