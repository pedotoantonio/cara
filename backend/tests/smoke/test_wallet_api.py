"""Smoke tests for /api/v1/wallet/*."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- auth


async def test_get_layout_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/wallet/layout?surface=mobile")
    assert r.status_code == 401, r.text


async def test_put_layout_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.put(
        "/api/v1/wallet/layout?surface=mobile", json={"items": []},
    )
    assert r.status_code == 401, r.text


async def test_list_presets_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/wallet/presets")
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------- surface validation


async def test_layout_validates_surface_query(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/wallet/layout?surface=fridge")
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------- defaults


async def test_layout_default_returned_when_no_row(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get("/api/v1/wallet/layout?surface=desktop")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["surface_class"] == "desktop"
    assert body["is_default"] is True
    assert body["items"]   # default isn't empty


# ---------------------------------------------------------------- put / replace


async def test_put_layout_round_trip(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.put(
        "/api/v1/wallet/layout?surface=mobile",
        json={"items": [
            {"widget_id": "tasks_mine", "size": "medium", "config": {}},
            {"widget_id": "weather_now", "size": "small", "config": {}},
        ]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preset"] == "custom"
    assert [i["widget_id"] for i in body["items"]] == ["tasks_mine", "weather_now"]

    # GET picks it back up.
    r = await auth_client.get("/api/v1/wallet/layout?surface=mobile")
    assert r.status_code == 200
    assert r.json()["is_default"] is False


async def test_put_layout_drops_malformed_entries(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.put(
        "/api/v1/wallet/layout?surface=mobile",
        json={"items": [
            {"widget_id": "valid_id", "size": "medium", "config": {}},
            {"widget_id": "valid_id", "size": "small", "config": {}},  # duplicate
        ]},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    # Duplicates collapsed to one.
    assert len([i for i in items if i["widget_id"] == "valid_id"]) == 1


async def test_put_layout_validates_size_via_pydantic(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.put(
        "/api/v1/wallet/layout?surface=mobile",
        json={"items": [
            {"widget_id": "x", "size": "huge"},  # invalid pattern
        ]},
    )
    assert r.status_code == 422, r.text


async def test_put_layout_caps_max_items(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.put(
        "/api/v1/wallet/layout?surface=mobile",
        json={"items": [
            {"widget_id": f"w{i}", "size": "small"} for i in range(40)
        ]},
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------- delete reset


async def test_delete_layout_resets_to_default(
    auth_client: httpx.AsyncClient,
) -> None:
    # Seed something custom first.
    await auth_client.put(
        "/api/v1/wallet/layout?surface=desktop",
        json={"items": [{"widget_id": "tasks_mine", "size": "small"}]},
    )
    # Then reset.
    r = await auth_client.delete("/api/v1/wallet/layout?surface=desktop")
    assert r.status_code == 204, r.text
    # Read-back must be the default again.
    r = await auth_client.get("/api/v1/wallet/layout?surface=desktop")
    assert r.json()["is_default"] is True


# ---------------------------------------------------------------- presets


async def test_list_presets_returns_four(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/wallet/presets")
    assert r.status_code == 200, r.text
    presets = r.json()
    slugs = {p["slug"] for p in presets}
    assert slugs == {"genitore", "teen", "bambino", "anziano"}


async def test_apply_preset_writes_layout(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/wallet/preset/genitore?surface=mobile",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preset"] == "genitore"
    assert body["is_default"] is False
    # Genitore preset must include today_summary.
    assert any(i["widget_id"] == "today_summary" for i in body["items"])


async def test_apply_unknown_preset_404(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/wallet/preset/non_esiste?surface=mobile",
    )
    assert r.status_code == 404, r.text


async def test_apply_preset_requires_surface_query(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.post("/api/v1/wallet/preset/genitore")
    assert r.status_code == 422, r.text
