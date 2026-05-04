"""Weather endpoints — wrap the Open-Meteo client (`cara.services.weather`).

Three operations:

  GET /api/v1/weather/geocode?q=<city>          → list of candidate locations
  GET /api/v1/weather/current?lat=&lon=         → current conditions + WMO icon
  GET /api/v1/weather/forecast?lat=&lon=&days=  → daily forecast for N days

All endpoints require auth (the chat layer / Wallet calls them with the
user's bearer token). They never reach the LLM and never write data,
so rate-limiting is a single layer concern — handled by Redis cache
inside the service.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.services.weather import WeatherService


router = APIRouter(prefix="/weather", tags=["weather"])


# Process-wide service instance. Lazy-created on first use so the
# httpx client (and its event loop) is bound to the running app, not
# the module import.
_service: WeatherService | None = None


def _get_service() -> WeatherService:
    global _service
    if _service is None:
        # Redis client wiring lands when we adopt a shared
        # `cara.services.cache_factory` (one Redis client per process).
        # For now the weather cache stays a no-op — Open-Meteo has no
        # rate limits anyway.
        _service = WeatherService()
    return _service


@router.get("/geocode")
async def geocode(
    q: str = Query(..., min_length=1, max_length=80, description="City name"),
    count: int = Query(default=5, ge=1, le=10),
    _user: User = Depends(get_current_user),  # auth required
) -> dict[str, Any]:
    """Resolve a city name to a list of (name, country, lat, lon, timezone)."""
    svc = _get_service()
    results = await svc.geocode(q.strip(), count=count)
    return {
        "query": q,
        "results": [r.to_dict() for r in results],
    }


@router.get("/current")
async def current(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    timezone: str = Query(default="auto", max_length=64),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Current weather. Returns 503 if Open-Meteo is unreachable."""
    svc = _get_service()
    cur = await svc.current(lat, lon, timezone=timezone)
    if cur is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "weather provider unreachable",
        )
    return cur.to_dict()


@router.get("/forecast")
async def forecast(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    days: int = Query(default=5, ge=1, le=7),
    timezone: str = Query(default="auto", max_length=64),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Daily forecast for the next `days`. Empty list when unreachable."""
    svc = _get_service()
    forecast_rows = await svc.forecast(lat, lon, days=days, timezone=timezone)
    return {
        "lat": lat,
        "lon": lon,
        "days": days,
        "items": [d.to_dict() for d in forecast_rows],
    }
