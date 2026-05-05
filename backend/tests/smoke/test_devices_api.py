"""Smoke tests for the device pairing flow.

The flow is:
  1. anonymous POST /devices/pair/start   → {code, expires_at}
  2. anonymous GET  /devices/pair/status  → {status: "waiting"} initially
  3. admin     POST /devices/pair/finalize→ Device row created
  4. anonymous GET  /devices/pair/status  → {status: "paired", device_token}
  5. admin     GET  /devices              → list contains the new device
  6. admin     PATCH /devices/{id}        → rename, change surface, etc.
  7. admin     DELETE /devices/{id}       → deauth + remove row
"""

from __future__ import annotations

import pytest

API = "/api/v1"


@pytest.mark.asyncio
async def test_pair_start_returns_six_digit_code(http) -> None:
    r = await http.post(f"{API}/devices/pair/start", json={})
    if r.status_code == 503:
        pytest.skip("Redis non disponibile per il pairing")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "code" in body and len(body["code"]) == 6 and body["code"].isdigit()
    assert "expires_at" in body


@pytest.mark.asyncio
async def test_pair_status_unknown_code_is_expired(http) -> None:
    r = await http.get(f"{API}/devices/pair/status", params={"code": "000000"})
    if r.status_code == 503:
        pytest.skip("Redis non disponibile per il pairing")
    assert r.status_code == 200
    assert r.json()["status"] == "expired"


@pytest.mark.asyncio
async def test_pair_status_validates_code_length(http) -> None:
    r = await http.get(f"{API}/devices/pair/status", params={"code": "123"})
    # FastAPI validation rejects with 422 before we get to the handler.
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_devices_list_requires_admin(http, auth_client) -> None:
    """Non-admin users get 403."""
    if auth_client is None:
        pytest.skip("auth_client fixture not available")
    r = await auth_client.get(f"{API}/devices")
    # Either 401 (unauth) or 403 (non-admin) is acceptable.
    assert r.status_code in (401, 403), r.text


@pytest.mark.asyncio
async def test_pair_finalize_requires_admin(http) -> None:
    """No bearer at all → 401."""
    r = await http.post(
        f"{API}/devices/pair/finalize",
        json={
            "code": "000000",
            "friendly_name": "Test Device",
            "surface_class": "mobile",
        },
    )
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_pair_finalize_rejects_invalid_surface(http, admin_client) -> None:
    """Even with a valid code, an invalid surface_class is 400."""
    if admin_client is None:
        pytest.skip("admin_client fixture not available")

    # First start a pairing so the code is valid.
    start = await http.post(f"{API}/devices/pair/start", json={})
    if start.status_code == 503:
        pytest.skip("Redis non disponibile per il pairing")
    code = start.json()["code"]

    r = await admin_client.post(
        f"{API}/devices/pair/finalize",
        json={
            "code": code,
            "friendly_name": "X",
            "surface_class": "spaceship",  # invalid
        },
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_full_pair_then_status_then_delete(http, admin_client) -> None:
    if admin_client is None:
        pytest.skip("admin_client fixture not available")

    # 1) start
    start = await http.post(
        f"{API}/devices/pair/start",
        json={"suggested_name": "Wall soggiorno", "suggested_surface": "wall"},
    )
    if start.status_code == 503:
        pytest.skip("Redis non disponibile per il pairing")
    code = start.json()["code"]

    # 2) waiting before admin finalises
    status1 = await http.get(f"{API}/devices/pair/status", params={"code": code})
    assert status1.status_code == 200
    assert status1.json()["status"] == "waiting"

    # 3) admin finalises
    fin = await admin_client.post(
        f"{API}/devices/pair/finalize",
        json={
            "code": code,
            "friendly_name": "Wall soggiorno",
            "surface_class": "wall",
            "location": "soggiorno",
        },
    )
    assert fin.status_code == 201, fin.text
    device_id = fin.json()["id"]
    assert fin.json()["surface_class"] == "wall"
    assert fin.json()["status"] == "pending"

    try:
        # 4) device now sees status=paired + token
        status2 = await http.get(
            f"{API}/devices/pair/status", params={"code": code},
        )
        assert status2.status_code == 200
        body = status2.json()
        assert body["status"] == "paired"
        assert body["device_token"] is not None and len(body["device_token"]) > 50
        assert body["device_id"] == device_id

        # 4b) second poll consumes nothing extra (key was deleted)
        status3 = await http.get(
            f"{API}/devices/pair/status", params={"code": code},
        )
        assert status3.json()["status"] == "expired"

        # 5) admin sees it in the list
        ls = await admin_client.get(f"{API}/devices")
        assert ls.status_code == 200
        ids = [d["id"] for d in ls.json()]
        assert device_id in ids

        # 6) admin renames + flips off
        patch = await admin_client.patch(
            f"{API}/devices/{device_id}",
            json={"friendly_name": "Wall salotto", "enabled": False},
        )
        assert patch.status_code == 200
        assert patch.json()["friendly_name"] == "Wall salotto"
        assert patch.json()["enabled"] is False
    finally:
        # 7) cleanup — delete
        rd = await admin_client.delete(f"{API}/devices/{device_id}")
        assert rd.status_code == 204
