"""Task CRUD round-trip.

Creates a task, lists it back, marks it done, deletes it. This is the
smallest integration that exercises auth → ORM session → service → response.
"""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_task_full_crud(auth_client: httpx.AsyncClient) -> None:
    # CREATE
    create = await auth_client.post(
        "/api/v1/tasks",
        json={"title": "Comprare il pane (smoke test)"},
    )
    assert create.status_code == 201, create.text
    task = create.json()
    task_id = task["id"]
    assert task["title"] == "Comprare il pane (smoke test)"
    assert task["done"] is False

    try:
        # LIST — the new task must show up
        listing = await auth_client.get("/api/v1/tasks")
        assert listing.status_code == 200, listing.text
        ids = [t["id"] for t in listing.json()]
        assert task_id in ids

        # PATCH — mark done
        patched = await auth_client.patch(
            f"/api/v1/tasks/{task_id}",
            json={"done": True},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["done"] is True
    finally:
        # DELETE — always clean up so the user's task list isn't polluted
        delete = await auth_client.delete(f"/api/v1/tasks/{task_id}")
        assert delete.status_code == 204, delete.text


async def test_task_create_requires_title(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/api/v1/tasks", json={"title": ""})
    assert r.status_code == 422, r.text


async def test_task_unauthorized_without_token(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/tasks")
    assert r.status_code == 401, r.text
