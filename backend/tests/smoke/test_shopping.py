"""Shopping list CRUD + clear-bought sweep."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_shopping_full_crud(auth_client: httpx.AsyncClient) -> None:
    # CREATE
    create = await auth_client.post(
        "/api/v1/shopping",
        json={"title": "Latte intero", "qty": "2 L"},
    )
    assert create.status_code == 201, create.text
    item = create.json()
    item_id = item["id"]
    assert item["title"] == "Latte intero"
    assert item["bought"] is False

    try:
        # LIST contains it
        listing = await auth_client.get("/api/v1/shopping")
        assert listing.status_code == 200
        assert any(i["id"] == item_id for i in listing.json())

        # PATCH bought=True
        patched = await auth_client.patch(
            f"/api/v1/shopping/{item_id}",
            json={"bought": True},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["bought"] is True

        # CLEAR-BOUGHT removes it
        sweep = await auth_client.post("/api/v1/shopping/clear-bought")
        assert sweep.status_code in (200, 204), sweep.text

        listing = await auth_client.get("/api/v1/shopping")
        assert all(i["id"] != item_id for i in listing.json()), (
            "clear-bought did not remove the bought item"
        )
    finally:
        # In case clear-bought changes shape, fall back to explicit delete.
        await auth_client.delete(f"/api/v1/shopping/{item_id}")


async def test_shopping_unauthorized(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/shopping")
    assert r.status_code == 401, r.text
