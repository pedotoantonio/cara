"""Smoke tests for /api/v1/{budgets,expenses}/*."""

from __future__ import annotations

from datetime import date

import httpx
import pytest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- auth gates


async def test_list_budgets_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/budgets/2026/5")
    assert r.status_code == 401, r.text


async def test_add_expense_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.post(
        "/api/v1/expenses",
        json={"spent_on": "2026-05-04", "amount_cents": 1000, "category": "groceries"},
    )
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------- budget upsert


async def test_upsert_budget_round_trip(auth_client: httpx.AsyncClient) -> None:
    # PUT creates.
    r = await auth_client.put(
        "/api/v1/budgets/2026/5/groceries",
        json={"target_amount_cents": 50000, "note": "smoke test"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "groceries"
    assert body["target_amount_cents"] == 50000
    assert body["note"] == "smoke test"

    # PUT updates idempotently.
    r2 = await auth_client.put(
        "/api/v1/budgets/2026/5/groceries",
        json={"target_amount_cents": 60000},
    )
    assert r2.status_code == 200
    assert r2.json()["target_amount_cents"] == 60000

    # LIST returns it.
    r3 = await auth_client.get("/api/v1/budgets/2026/5")
    assert r3.status_code == 200
    cats = [b["category"] for b in r3.json()]
    assert "groceries" in cats


async def test_upsert_budget_validates_month(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.put(
        "/api/v1/budgets/2026/13/groceries",
        json={"target_amount_cents": 1000},
    )
    assert r.status_code == 400, r.text


async def test_upsert_budget_validates_year(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.put(
        "/api/v1/budgets/1900/5/groceries",
        json={"target_amount_cents": 1000},
    )
    assert r.status_code == 400, r.text


async def test_upsert_budget_unknown_category_normalised_to_other(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.put(
        "/api/v1/budgets/2026/5/something_weird",
        json={"target_amount_cents": 1000},
    )
    assert r.status_code == 200
    # Unknown category is normalised to "other" by the service.
    assert r.json()["category"] == "other"


# ---------------------------------------------------------------- expenses CRUD


async def test_expense_crud_round_trip(auth_client: httpx.AsyncClient) -> None:
    today = date.today().isoformat()
    create = await auth_client.post(
        "/api/v1/expenses",
        json={
            "spent_on": today,
            "amount_cents": 1234,
            "category": "groceries",
            "vendor": "Smoke Test Conad",
        },
    )
    assert create.status_code == 201, create.text
    eid = create.json()["id"]

    try:
        # LIST contains it.
        listing = await auth_client.get("/api/v1/expenses")
        assert listing.status_code == 200
        ids = [e["id"] for e in listing.json()]
        assert eid in ids

        # FILTER by year + month finds it.
        y, m = today.split("-")[:2]
        scoped = await auth_client.get(
            f"/api/v1/expenses?year={y}&month={int(m)}",
        )
        assert any(e["id"] == eid for e in scoped.json())
    finally:
        delete = await auth_client.delete(f"/api/v1/expenses/{eid}")
        assert delete.status_code == 204


async def test_expense_validates_negative_amount(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/expenses",
        json={"spent_on": "2026-05-04", "amount_cents": -100, "category": "groceries"},
    )
    assert r.status_code == 422, r.text


async def test_delete_unknown_expense_returns_404(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.delete("/api/v1/expenses/99999999")
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------- month rollup


async def test_month_rollup_returns_empty_when_no_data(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get("/api/v1/budgets/2099/1/rollup")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["year"] == 2099
    assert body["month"] == 1
    assert body["total_spent_cents"] == 0
    assert body["categories"] == []


async def test_month_rollup_aggregates_expenses(
    auth_client: httpx.AsyncClient,
) -> None:
    """Add an expense, hit the rollup, see it land in the right category."""
    today = date.today()
    r = await auth_client.post(
        "/api/v1/expenses",
        json={
            "spent_on": today.isoformat(),
            "amount_cents": 999,
            "category": "groceries",
            "vendor": "rollup test",
        },
    )
    assert r.status_code == 201
    eid = r.json()["id"]

    try:
        rollup = await auth_client.get(
            f"/api/v1/budgets/{today.year}/{today.month}/rollup",
        )
        assert rollup.status_code == 200
        body = rollup.json()
        groceries = next(
            (c for c in body["categories"] if c["category"] == "groceries"),
            None,
        )
        assert groceries is not None
        assert groceries["spent_cents"] >= 999
        assert groceries["expense_count"] >= 1
    finally:
        await auth_client.delete(f"/api/v1/expenses/{eid}")
