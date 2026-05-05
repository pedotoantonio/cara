"""Smoke tests for /api/v1/widgets/*."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_list_widgets_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/widgets")
    assert r.status_code == 401, r.text


async def test_list_widgets_returns_catalog(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/widgets")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "widgets" in body
    ids = {w["id"] for w in body["widgets"]}
    # The shipped catalog (Step 7.2) registers these seven.
    expected = {
        "today_summary", "tasks_mine", "shopping_quick", "notes_recent",
        "weather_now", "presence", "quick_actions",
    }
    assert expected.issubset(ids), (expected, ids)


async def test_render_one_widget_returns_payload(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get("/api/v1/widgets/quick_actions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["widget_id"] == "quick_actions"
    assert body["kind"] == "action_grid"
    assert "actions" in body["body"]


async def test_render_unknown_widget_returns_404(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get("/api/v1/widgets/does_not_exist")
    assert r.status_code == 404, r.text


async def test_render_many_returns_in_request_order(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get(
        "/api/v1/widgets/render",
        params={"ids": "quick_actions,tasks_mine,weather_now"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    assert [i["widget_id"] for i in items] == [
        "quick_actions", "tasks_mine", "weather_now",
    ]


async def test_render_many_caps_size(auth_client: httpx.AsyncClient) -> None:
    """More than 32 widget ids → 400."""
    r = await auth_client.get(
        "/api/v1/widgets/render",
        params={"ids": ",".join(["x"] * 40)},
    )
    assert r.status_code == 400, r.text


async def test_render_many_no_ids(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get(
        "/api/v1/widgets/render",
        params={"ids": ",, ,"},
    )
    assert r.status_code == 400, r.text


async def test_render_invalid_surface_rejected(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get(
        "/api/v1/widgets/render",
        params={"ids": "quick_actions", "surface": "fridge"},
    )
    assert r.status_code == 422, r.text


async def test_render_unknown_widget_id_yields_inline_error_not_500(
    auth_client: httpx.AsyncClient,
) -> None:
    """A bogus id in `render?ids=` produces an inline error payload, not 500."""
    r = await auth_client.get(
        "/api/v1/widgets/render",
        params={"ids": "quick_actions,nonsense_widget"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(i.get("error") for i in items)
