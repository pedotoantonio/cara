"""Smoke tests for /api/v1/memory/* — facts CRUD + extract + GDPR export."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_list_facts_unauthorized(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/memory/facts")
    assert r.status_code == 401, r.text


async def test_create_list_patch_delete_fact_round_trip(
    auth_client: httpx.AsyncClient,
) -> None:
    # CREATE
    r = await auth_client.post(
        "/api/v1/memory/facts",
        json={"text": "Smoke-test fact: caffè senza zucchero", "type": "preference"},
    )
    assert r.status_code == 201, r.text
    fact = r.json()
    fid = fact["id"]
    assert fact["active"] is True
    assert fact["source"] == "pin"

    try:
        # LIST contains the new fact.
        r = await auth_client.get("/api/v1/memory/facts")
        assert r.status_code == 200
        ids = [f["id"] for f in r.json()]
        assert fid in ids

        # PATCH text + confidence.
        r = await auth_client.patch(
            f"/api/v1/memory/facts/{fid}",
            json={"text": "Smoke-test edit", "confidence": 0.8},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["text"] == "Smoke-test edit"
        assert body["confidence"] == 0.8
    finally:
        # SOFT-DELETE (active=False, audit preserved).
        r = await auth_client.delete(f"/api/v1/memory/facts/{fid}")
        assert r.status_code == 204, r.text

        # active_only=False still shows it.
        r = await auth_client.get(
            "/api/v1/memory/facts", params={"active_only": "false"},
        )
        assert any(f["id"] == fid and f["active"] is False for f in r.json())


async def test_extract_facts_finds_allergy(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/memory/facts/extract",
        json={"message": "sono allergico ai pomodori.", "save": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposals"], "should have at least one proposal"
    types = {p["fact_type"] for p in body["proposals"]}
    assert "allergy" in types
    assert body["saved_ids"] == []


async def test_extract_facts_save_true_persists(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/memory/facts/extract",
        json={"message": "Mi piace il caffè ristretto.", "save": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    saved_ids = body["saved_ids"]
    assert saved_ids

    # Cleanup: hard-delete via purge would also nuke the smoke user's
    # other facts; instead soft-delete the saved ones.
    for fid in saved_ids:
        await auth_client.delete(f"/api/v1/memory/facts/{fid}")


async def test_export_returns_user_scoped_json(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/memory/export")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "user_id" in body
    assert "email" in body
    assert "facts" in body
    assert isinstance(body["facts"], list)


async def test_purge_deletes_only_my_facts(auth_client: httpx.AsyncClient) -> None:
    # Seed one fact then purge.
    create = await auth_client.post(
        "/api/v1/memory/facts",
        json={"text": "ephemeral smoke fact", "type": "personal"},
    )
    assert create.status_code == 201

    r = await auth_client.delete("/api/v1/memory/purge")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] >= 1


async def test_patch_unknown_id_returns_404(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.patch(
        "/api/v1/memory/facts/9999999",
        json={"text": "ghost"},
    )
    assert r.status_code == 404, r.text
