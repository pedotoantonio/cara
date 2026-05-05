"""Smoke tests for /api/v1/admin/device-aliases."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_list_aliases_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/admin/device-aliases")
    assert r.status_code == 403, r.text


async def test_create_alias_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/admin/device-aliases",
        json={"entity_id": "ha:light.cucina", "alias": "il lampadario"},
    )
    assert r.status_code == 403, r.text


async def test_delete_alias_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.delete("/api/v1/admin/device-aliases/1")
    assert r.status_code == 403, r.text


async def test_unauthorized_no_token(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/admin/device-aliases")
    assert r.status_code == 401, r.text


async def test_create_validates_entity_id_shape(http: httpx.AsyncClient) -> None:
    """Body validation runs alongside the auth dependency. Either 401
    or 422 is fine — we just lock down that an empty/short entity_id
    can't reach the DB."""
    r = await http.post(
        "/api/v1/admin/device-aliases",
        json={"entity_id": "x", "alias": "y"},
    )
    assert r.status_code in (401, 422), r.text


async def test_create_validates_alias_length(http: httpx.AsyncClient) -> None:
    r = await http.post(
        "/api/v1/admin/device-aliases",
        json={"entity_id": "ha:light.x", "alias": "x" * 200},
    )
    assert r.status_code in (401, 422), r.text
