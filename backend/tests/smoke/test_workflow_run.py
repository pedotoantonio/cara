"""Smoke tests for the workflow engine end-to-end via /api/v1/workflows/run.

The receipt workflow is the canonical happy path: an OCR text from a
typical Italian till receipt should classify as `receipt`, parse vendor
+ total + items + date, and propose at least one action.
"""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- run


async def test_run_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.post("/api/v1/workflows/run", json={"text": "x"})
    assert r.status_code == 401, r.text


async def test_run_empty_body_400(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/api/v1/workflows/run", json={})
    assert r.status_code == 400, r.text


async def test_receipt_dispatch_and_propose(auth_client: httpx.AsyncClient) -> None:
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
    assert body["structured"]["vendor"]
    assert body["structured"]["date"]
    assert body["proposed_actions"], "expected at least one proposed action"
    # Each proposed action should have a signature (used for auto-confirm).
    for a in body["proposed_actions"]:
        assert "signature" in a
        assert "auto_confirmable" in a


async def test_receipt_confirmed_executes(auth_client: httpx.AsyncClient) -> None:
    """When `confirmed=True` the engine actually applies the side effects."""
    text = (
        "CONAD CITY\n"
        "Data: 03/05/2026\n"
        "ZUCCHERO 1,99\n"
        "TOTALE 1,99\n"
    )
    r = await auth_client.post(
        "/api/v1/workflows/run",
        json={"ocr_text": text, "confirmed": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"] is True
    # When confirmed, the response carries `executed=True`.
    assert body.get("executed") is True


async def test_random_text_no_match(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/workflows/run",
        json={"text": "ciao come stai oggi?"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["matched"] is False


async def test_invalid_image_b64_400(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/workflows/run",
        json={"image_b64": "@@@not-base64@@@"},
    )
    assert r.status_code == 400, r.text
