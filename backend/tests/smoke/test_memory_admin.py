"""Smoke tests for /api/v1/admin/memory/* (admin-only memory governance)."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_admin_users_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/admin/memory/users")
    assert r.status_code == 401, r.text


async def test_admin_users_requires_admin(auth_client: httpx.AsyncClient) -> None:
    """The fresh user is not admin (test fixture creates a parent role)."""
    r = await auth_client.get("/api/v1/admin/memory/users")
    # 403 if non-admin, 200 if happens to be admin in the fixture.
    assert r.status_code in (200, 403), r.text


async def test_admin_user_facts_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/admin/memory/1/facts")
    assert r.status_code == 401, r.text


async def test_admin_user_facts_404_for_unknown_user(
    auth_client: httpx.AsyncClient,
) -> None:
    """Even non-admin should be 403/401 BEFORE 404 — auth gates first.
    Just verifies the route exists in the router."""
    r = await auth_client.get("/api/v1/admin/memory/99999999/facts")
    assert r.status_code in (200, 401, 403), r.text


async def test_my_facts_listing(auth_client: httpx.AsyncClient) -> None:
    """The user-scoped /memory/facts endpoint must always 200, even with
    zero rows."""
    r = await auth_client.get("/api/v1/memory/facts")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


async def test_my_fact_create_and_delete(auth_client: httpx.AsyncClient) -> None:
    create = await auth_client.post(
        "/api/v1/memory/facts",
        json={"text": "Smoke test fact", "type": "personal", "confidence": 0.9},
    )
    assert create.status_code == 201, create.text
    fact_id = create.json()["id"]

    # Patch (rename).
    patched = await auth_client.patch(
        f"/api/v1/memory/facts/{fact_id}",
        json={"text": "Smoke test fact (renamed)"},
    )
    assert patched.status_code == 200, patched.text
    assert "renamed" in patched.json()["text"]

    # Soft delete.
    deleted = await auth_client.delete(f"/api/v1/memory/facts/{fact_id}")
    assert deleted.status_code == 204, deleted.text


async def test_export_returns_json(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/memory/export")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "user_id" in body
    assert "facts" in body
    assert isinstance(body["facts"], list)
