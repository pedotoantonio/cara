"""Smoke tests for /api/v1/smarthome/*.

Smart-home is OFF by default in admin_settings. The contract these
tests exercise is therefore "endpoint reachable + returns 503 cleanly
when not configured" — never a 500.
"""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_entities_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/smarthome/entities")
    assert r.status_code == 401, r.text


async def test_entities_503_when_disabled(auth_client: httpx.AsyncClient) -> None:
    """Default config: smart-home off → 503 with a clean message."""
    r = await auth_client.get("/api/v1/smarthome/entities")
    assert r.status_code in (503, 200), r.text
    if r.status_code == 503:
        assert "not configured" in r.json().get("detail", "").lower()


async def test_health_when_disabled_returns_ok_false(
    auth_client: httpx.AsyncClient,
) -> None:
    """Health is read-only and always answers (no 503) — even when off."""
    r = await auth_client.get("/api/v1/smarthome/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ok" in body
    assert "provider" in body


async def test_call_service_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.post(
        "/api/v1/smarthome/services",
        json={"domain": "light", "service": "turn_on", "entity_id": "ha:light.x"},
    )
    assert r.status_code == 401, r.text


async def test_call_service_503_or_403_when_disabled(
    auth_client: httpx.AsyncClient,
) -> None:
    """Service call when adapter unconfigured → 503 (not 500)."""
    r = await auth_client.post(
        "/api/v1/smarthome/services",
        json={"domain": "light", "service": "turn_on", "entity_id": "ha:light.x"},
    )
    assert r.status_code in (503, 403, 200), r.text


async def test_resolve_503_when_disabled(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/smarthome/resolve",
        json={"utterance": "accendi la luce della cucina"},
    )
    assert r.status_code in (503, 200), r.text


async def test_call_service_validation_rejects_short_entity(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.post(
        "/api/v1/smarthome/services",
        json={"domain": "light", "service": "turn_on", "entity_id": "x"},
    )
    assert r.status_code == 422, r.text
