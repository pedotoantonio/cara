"""Conversation CRUD smoke test (no streaming chat — that's Step 0.4)."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_conversation_create_list_fetch_delete(
    auth_client: httpx.AsyncClient,
) -> None:
    create = await auth_client.post(
        "/api/v1/conversations",
        json={"title": "Smoke test conversation"},
    )
    assert create.status_code == 201, create.text
    conv = create.json()
    conv_id = conv["id"]

    try:
        listing = await auth_client.get("/api/v1/conversations")
        assert listing.status_code == 200
        assert any(c["id"] == conv_id for c in listing.json())

        detail = await auth_client.get(f"/api/v1/conversations/{conv_id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["id"] == conv_id
        # A brand-new conversation has no messages.
        assert "messages" in body
        assert body["messages"] == []
    finally:
        delete = await auth_client.delete(f"/api/v1/conversations/{conv_id}")
        assert delete.status_code == 204, delete.text


async def test_conversation_unauthorized(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/conversations")
    assert r.status_code == 401, r.text
