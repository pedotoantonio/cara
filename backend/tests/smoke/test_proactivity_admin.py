"""Smoke tests for /api/v1/admin/proactivity/*."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_rules_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/admin/proactivity/rules")
    assert r.status_code == 401, r.text


async def test_rules_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/admin/proactivity/rules")
    assert r.status_code in (200, 403), r.text
    if r.status_code == 200:
        rows = r.json()
        assert isinstance(rows, list)
        # At least the 6 baseline rules are loaded.
        ids = {r["rule_id"] for r in rows}
        assert "morning_greeting" in ids
        assert "undone_tasks_evening" in ids
        assert "rain_alert" in ids


async def test_run_now_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.post("/api/v1/admin/proactivity/run-now")
    assert r.status_code == 401, r.text


async def test_run_now_returns_count(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/api/v1/admin/proactivity/run-now")
    assert r.status_code in (200, 403), r.text
    if r.status_code == 200:
        body = r.json()
        assert "count" in body
        assert "suggestions" in body
        assert isinstance(body["suggestions"], list)


async def test_toggle_unknown_rule_404(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/admin/proactivity/rules/nonexistent_rule/toggle?enabled=false"
    )
    assert r.status_code in (403, 404), r.text
