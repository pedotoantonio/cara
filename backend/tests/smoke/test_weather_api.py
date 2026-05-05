"""Smoke tests for /api/v1/weather/*. Hits Open-Meteo for real."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_geocode_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/weather/geocode", params={"q": "Roma"})
    assert r.status_code == 401, r.text


async def test_geocode_resolves_known_city(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/weather/geocode", params={"q": "Roma"})
    # Accept 200 (Open-Meteo reachable) or 503 (network blocked); the CARA
    # endpoint must NEVER 5xx with an unhandled exception.
    assert r.status_code in (200, 503), r.text
    if r.status_code == 200:
        body = r.json()
        assert body["query"] == "Roma"
        assert isinstance(body["results"], list)


async def test_current_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get(
        "/api/v1/weather/current",
        params={"lat": 41.89, "lon": 12.49},
    )
    assert r.status_code == 401, r.text


async def test_current_returns_payload_or_503(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get(
        "/api/v1/weather/current",
        params={"lat": 41.89, "lon": 12.49},
    )
    # 503 if Open-Meteo unreachable from the host network. Both are valid.
    assert r.status_code in (200, 503), r.text
    if r.status_code == 200:
        body = r.json()
        assert "temperature_c" in body
        assert "weather_code" in body
        assert "icon_slug" in body
