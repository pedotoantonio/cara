"""Smoke tests for /api/v1/admin/{habits,reflective,tool-metrics}/*.

Smoke-test contract: endpoints exist, gate non-admin users out, and
return reasonable shapes when reachable. We don't have an admin
fixture in the smoke suite — the auto-registered test user is a
plain parent — so the happy paths are exercised by unit tests in
the underlying modules. Here we lock down the gate-keeping.
"""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- habits


async def test_habits_detect_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.post("/api/v1/admin/habits/detect", json={"lookback_days": 30})
    assert r.status_code == 401, r.text


async def test_habits_detect_requires_admin(auth_client: httpx.AsyncClient) -> None:
    """Plain user → 403, never 200 / never crash."""
    r = await auth_client.post("/api/v1/admin/habits/detect", json={"lookback_days": 30})
    assert r.status_code == 403, r.text


async def test_habits_candidates_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/admin/habits/candidates")
    assert r.status_code == 403, r.text


async def test_habits_review_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/admin/habits/1/review",
        json={"decision": "accept"},
    )
    assert r.status_code == 403, r.text


async def test_habits_detect_validates_lookback(http: httpx.AsyncClient) -> None:
    """Body validation runs before the auth dependency in FastAPI's
    default ordering — so we can probe schema without a real admin."""
    r = await http.post(
        "/api/v1/admin/habits/detect",
        json={"lookback_days": 9999},  # > 365 ceiling
    )
    # Either 401 (auth first) or 422 (validation first) — both are clean.
    assert r.status_code in (401, 422), r.text


async def test_habits_review_validates_decision(http: httpx.AsyncClient) -> None:
    r = await http.post(
        "/api/v1/admin/habits/1/review",
        json={"decision": "approve_maybe"},
    )
    assert r.status_code in (401, 422), r.text


# ---------------------------------------------------------------- reflective


async def test_reflective_run_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/admin/reflective/run",
        json={"since_days": 7},
    )
    assert r.status_code == 403, r.text


async def test_reflective_run_validates_since_days(http: httpx.AsyncClient) -> None:
    r = await http.post(
        "/api/v1/admin/reflective/run",
        json={"since_days": 9999},  # > 180 ceiling
    )
    assert r.status_code in (401, 422), r.text


# ---------------------------------------------------------------- tool-metrics


async def test_tool_metrics_stats_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/admin/tool-metrics/stats")
    assert r.status_code == 403, r.text


async def test_tool_metrics_top_failures_requires_admin(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get("/api/v1/admin/tool-metrics/top-failures")
    assert r.status_code == 403, r.text


async def test_tool_metrics_recent_requires_admin(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get("/api/v1/admin/tool-metrics/recent")
    assert r.status_code == 403, r.text


async def test_tool_metrics_unauthorized_no_token(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/admin/tool-metrics/stats")
    assert r.status_code == 401, r.text
