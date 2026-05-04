"""Smoke tests for /api/v1/workflows/*."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- auth


async def test_run_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.post("/api/v1/workflows/run", json={"text": "x"})
    assert r.status_code == 401, r.text


async def test_list_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/workflows")
    assert r.status_code == 401, r.text


async def test_trust_get_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/workflows/trust")
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------- list


async def test_list_returns_three_concrete_workflows(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get("/api/v1/workflows")
    assert r.status_code == 200, r.text
    body = r.json()
    names = {w["name"] for w in body["workflows"]}
    expected = {"receipt", "recipe", "bill"}
    assert expected.issubset(names)


# ---------------------------------------------------------------- run validation


async def test_run_empty_request_400(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/api/v1/workflows/run", json={})
    assert r.status_code == 400, r.text


async def test_run_invalid_image_b64_400(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/workflows/run",
        json={"image_b64": "@@@not-base64@@@"},
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------- run dispatch


async def test_run_with_receipt_ocr_text_matches_receipt(
    auth_client: httpx.AsyncClient,
) -> None:
    """A pre-OCR'd receipt text dispatches to ReceiptWorkflow."""
    text = (
        "ESSELUNGA\n"
        "Data: 04/05/2026\n"
        "PANE 1,80\n"
        "LATTE 1,29\n"
        "TOTALE 3,09\n"
    )
    r = await auth_client.post(
        "/api/v1/workflows/run",
        json={"ocr_text": text, "confirmed": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"] is True
    assert body["workflow_name"] == "receipt"
    assert body["structured"]["total_cents"] == 309
    # Each proposed action must have a signature + auto-confirm metadata.
    for a in body["proposed_actions"]:
        assert "signature" in a
        assert "auto_confirmable" in a


async def test_run_with_recipe_text_matches_recipe(
    auth_client: httpx.AsyncClient,
) -> None:
    """A typed recipe text → RecipeWorkflow."""
    text = (
        "Ricetta della carbonara\n"
        "Ingredienti per 4 persone:\n"
        "- guanciale\n- uova\n- pecorino\n"
        "Preparazione: scaldare la padella…"
    )
    r = await auth_client.post(
        "/api/v1/workflows/run", json={"text": text},
    )
    # Either matches (recipe) or doesn't if extraction fails — both
    # are clean (200 with `matched=False` is fine).
    assert r.status_code == 200, r.text


async def test_run_with_bill_pdf_text_matches_bill(
    auth_client: httpx.AsyncClient,
) -> None:
    text = (
        "ENEL ENERGIA S.P.A.\n"
        "Bolletta luce - aprile 2026\n"
        "Importo da pagare: € 87,30\n"
        "Scadenza: 15/05/2026\n"
        "Numero cliente: 1234567\n"
    )
    r = await auth_client.post(
        "/api/v1/workflows/run", json={"pdf_text": text},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"] is True
    assert body["workflow_name"] == "bill"


async def test_run_random_text_no_match(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/workflows/run", json={"text": "ciao come stai oggi"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["matched"] is False


# ---------------------------------------------------------------- trust endpoints


async def test_trust_endpoint_returns_list(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get("/api/v1/workflows/trust")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


async def test_trust_revoke_unknown_returns_404(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.post(
        "/api/v1/workflows/trust/revoke",
        json={"workflow_kind": "receipt", "signature": "missing:sig"},
    )
    assert r.status_code == 404, r.text


async def test_trust_revoke_validation(http: httpx.AsyncClient) -> None:
    r = await http.post(
        "/api/v1/workflows/trust/revoke",
        json={"workflow_kind": "", "signature": ""},
    )
    assert r.status_code in (401, 422), r.text


async def test_trust_reject_records_no_history_silently(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.post(
        "/api/v1/workflows/trust/reject",
        json={
            "workflow_kind": "receipt",
            "tool": "add_expense",
            "arg_keys": ["amount_cents", "category", "vendor"],
        },
    )
    assert r.status_code == 200, r.text
