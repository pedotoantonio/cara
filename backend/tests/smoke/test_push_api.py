"""Smoke tests for /api/v1/push/*."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- public-key


async def test_public_key_no_auth(http: httpx.AsyncClient) -> None:
    """The public-key endpoint MUST be reachable without auth — the
    SW reads it before the user is even logged in."""
    r = await http.get("/api/v1/push/public-key")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "public_key" in body
    assert "configured" in body


# ---------------------------------------------------------------- subscribe


async def test_subscribe_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.post("/api/v1/push/subscribe", json={
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-aaaa",
        "keys": {"p256dh": "x" * 80, "auth": "y" * 24},
    })
    assert r.status_code == 401, r.text


async def test_subscribe_lifecycle(auth_client: httpx.AsyncClient) -> None:
    body = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-smoke-lifecycle",
        "keys": {
            "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
            "auth": "tBHItJI5svbpez7KI4CCXg",
        },
        "user_agent": "smoke-test",
    }
    r = await auth_client.post("/api/v1/push/subscribe", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("created", "updated")

    # Listing should now return at least one subscription.
    r = await auth_client.get("/api/v1/push/subscriptions")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(row.get("user_agent") == "smoke-test" for row in rows)

    # Unsubscribe.
    r = await auth_client.request(
        "DELETE", "/api/v1/push/subscribe",
        json={"endpoint": body["endpoint"]},
    )
    assert r.status_code in (200, 204), r.text


# ---------------------------------------------------------------- test


async def test_push_test_endpoint_authed(auth_client: httpx.AsyncClient) -> None:
    """POST /push/test must succeed when VAPID is configured. We don't
    care about delivery here (we have no real device); just the path."""
    r = await auth_client.post("/api/v1/push/test")
    # Either delivered=0 or the SDK reports a soft failure; both are fine.
    # If VAPID is not configured we get 503.
    assert r.status_code in (200, 503), r.text
    if r.status_code == 200:
        body = r.json()
        assert "delivered" in body
        assert "configured" in body
