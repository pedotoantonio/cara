"""Unit tests for `cara.services.weather`. No real network calls — we mock httpx."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from cara.services.weather import (
    CurrentWeather,
    DailyForecast,
    GeocodeResult,
    WeatherService,
    describe_wmo,
)


# ---------------------------------------------------------------- WMO mapping


def test_describe_wmo_known_codes() -> None:
    assert describe_wmo(0)["slug"] == "sun"
    assert describe_wmo(2)["slug"] == "cloud-sun"
    assert describe_wmo(63)["slug"] == "rain"
    assert describe_wmo(95)["slug"] == "thunderstorm"


def test_describe_wmo_unknown_falls_back_safely() -> None:
    out = describe_wmo(9999)
    assert out["slug"] == "unknown"
    assert out["label"] == "Sconosciuto"


def test_describe_wmo_none_input() -> None:
    out = describe_wmo(None)
    assert out["slug"] == "unknown"


# ---------------------------------------------------------------- helpers


def _mock_response(status: int, body: dict[str, Any]) -> MagicMock:
    """Build a MagicMock that quacks like httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = body
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------- geocoding


@pytest.mark.asyncio
async def test_geocode_parses_results() -> None:
    body = {
        "results": [
            {
                "name": "Roma",
                "country": "Italy",
                "latitude": 41.89,
                "longitude": 12.49,
                "timezone": "Europe/Rome",
                "admin1": "Lazio",
            },
            {
                "name": "Roma",
                "country": "USA",
                "latitude": 30.0,
                "longitude": -86.0,
                "timezone": "America/Chicago",
            },
        ]
    }
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(return_value=_mock_response(200, body))
    svc = WeatherService(http_client=http)

    out = await svc.geocode("Roma")
    assert len(out) == 2
    assert out[0].name == "Roma"
    assert out[0].country == "Italy"
    assert out[0].admin1 == "Lazio"


@pytest.mark.asyncio
async def test_geocode_empty_query_returns_empty() -> None:
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock()
    svc = WeatherService(http_client=http)
    out = await svc.geocode("   ")
    assert out == []
    http.get.assert_not_called()


@pytest.mark.asyncio
async def test_geocode_http_error_returns_empty() -> None:
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(side_effect=httpx.RequestError("network down"))
    svc = WeatherService(http_client=http)
    out = await svc.geocode("Roma")
    assert out == []


@pytest.mark.asyncio
async def test_geocode_skips_malformed_entries() -> None:
    body = {"results": [
        {"name": "Roma", "latitude": "not-a-float", "longitude": 12.49},  # bad
        {"name": "Milano", "latitude": 45.46, "longitude": 9.19, "timezone": "Europe/Rome"},
    ]}
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(return_value=_mock_response(200, body))
    svc = WeatherService(http_client=http)

    out = await svc.geocode("anything")
    assert len(out) == 1
    assert out[0].name == "Milano"


# ---------------------------------------------------------------- current


@pytest.mark.asyncio
async def test_current_parses_open_meteo_payload() -> None:
    body = {
        "current": {
            "time": "2026-05-04T11:00",
            "temperature_2m": 22.4,
            "apparent_temperature": 21.8,
            "relative_humidity_2m": 55,
            "wind_speed_10m": 8.2,
            "weather_code": 2,
            "is_day": 1,
        }
    }
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(return_value=_mock_response(200, body))
    svc = WeatherService(http_client=http)

    out = await svc.current(41.89, 12.49)
    assert isinstance(out, CurrentWeather)
    assert out.temperature_c == 22.4
    assert out.weather_code == 2
    assert out.icon_slug == "cloud-sun"
    assert out.is_day is True


@pytest.mark.asyncio
async def test_current_http_error_returns_none() -> None:
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(side_effect=httpx.RequestError("nope"))
    svc = WeatherService(http_client=http)
    out = await svc.current(0, 0)
    assert out is None


@pytest.mark.asyncio
async def test_current_malformed_body_returns_none() -> None:
    body = {"current": {"time": "2026-05-04T11:00"}}  # missing temperature
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(return_value=_mock_response(200, body))
    svc = WeatherService(http_client=http)
    out = await svc.current(0, 0)
    assert out is None


# ---------------------------------------------------------------- forecast


@pytest.mark.asyncio
async def test_forecast_parses_open_meteo_payload() -> None:
    body = {
        "daily": {
            "time": ["2026-05-04", "2026-05-05", "2026-05-06"],
            "temperature_2m_min": [12.0, 13.5, 14.0],
            "temperature_2m_max": [22.0, 24.0, 25.5],
            "weather_code": [0, 3, 61],
            "precipitation_sum": [0.0, 0.5, 4.2],
            "sunrise": ["2026-05-04T06:00", "2026-05-05T06:00", "2026-05-06T06:00"],
            "sunset": ["2026-05-04T20:30", "2026-05-05T20:31", "2026-05-06T20:32"],
        }
    }
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(return_value=_mock_response(200, body))
    svc = WeatherService(http_client=http)

    out = await svc.forecast(41.89, 12.49, days=3)
    assert len(out) == 3
    assert out[0].temp_max_c == 22.0
    assert out[2].weather_code == 61
    assert out[2].icon_slug == "rain"
    assert out[0].sunrise == "2026-05-04T06:00"


@pytest.mark.asyncio
async def test_forecast_clamps_days_to_seven() -> None:
    body = {"daily": {
        "time": [], "temperature_2m_min": [], "temperature_2m_max": [],
        "weather_code": [], "precipitation_sum": [], "sunrise": [], "sunset": [],
    }}
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(return_value=_mock_response(200, body))
    svc = WeatherService(http_client=http)
    await svc.forecast(0, 0, days=99)
    # Inspect what we actually requested — `forecast_days` should be capped to 7.
    call_kwargs = http.get.call_args.kwargs
    assert call_kwargs["params"]["forecast_days"] == 7


# ---------------------------------------------------------------- cache layer


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets = 0

    async def get(self, key):  # noqa: ANN001
        self.gets += 1
        return self.store.get(key)

    async def set(self, key, value, *, ex=None):  # noqa: ANN001, ARG002
        self.store[key] = value if isinstance(value, str) else value.decode()
        return True


@pytest.mark.asyncio
async def test_current_uses_cache_on_second_call() -> None:
    body = {"current": {
        "time": "2026-05-04T11:00", "temperature_2m": 22.4, "weather_code": 0, "is_day": 1
    }}
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(return_value=_mock_response(200, body))
    fake = FakeRedis()
    svc = WeatherService(redis_client=fake, http_client=http)

    a = await svc.current(41.89, 12.49)
    b = await svc.current(41.89, 12.49)

    assert a is not None and b is not None
    assert a.temperature_c == b.temperature_c
    # Network called once, cache hit second time.
    assert http.get.call_count == 1


@pytest.mark.asyncio
async def test_forecast_cache_key_separates_days() -> None:
    body = {"daily": {
        "time": [], "temperature_2m_min": [], "temperature_2m_max": [],
        "weather_code": [], "precipitation_sum": [], "sunrise": [], "sunset": [],
    }}
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(return_value=_mock_response(200, body))
    fake = FakeRedis()
    svc = WeatherService(redis_client=fake, http_client=http)

    await svc.forecast(41.89, 12.49, days=3)
    await svc.forecast(41.89, 12.49, days=5)
    # Different `days` → different cache slot → two network calls.
    assert http.get.call_count == 2


@pytest.mark.asyncio
async def test_cache_failure_does_not_break_request() -> None:
    body = {"current": {
        "time": "2026-05-04T11:00", "temperature_2m": 22.4, "weather_code": 0, "is_day": 1
    }}
    http = MagicMock(spec=httpx.AsyncClient)
    http.get = AsyncMock(return_value=_mock_response(200, body))

    bad_redis = MagicMock()
    bad_redis.get = AsyncMock(side_effect=RuntimeError("redis dead"))
    bad_redis.set = AsyncMock(side_effect=RuntimeError("redis dead"))

    svc = WeatherService(redis_client=bad_redis, http_client=http)
    out = await svc.current(0, 0)  # must not raise
    assert out is not None


# ---------------------------------------------------------------- dataclass round-trip


def test_geocode_to_dict_round_trip() -> None:
    g = GeocodeResult(name="Roma", country="Italy", latitude=41.89, longitude=12.49,
                     timezone="Europe/Rome", admin1="Lazio")
    d = g.to_dict()
    assert d["name"] == "Roma"
    assert d["latitude"] == 41.89
    # JSON-serialisable
    json.dumps(d)


def test_daily_to_dict_round_trip() -> None:
    f = DailyForecast(date="2026-05-04", temp_min_c=12.0, temp_max_c=22.0,
                     weather_code=0, icon_slug="sun", label="Sereno",
                     precipitation_mm=0.0, sunrise="06:00", sunset="20:30")
    json.dumps(f.to_dict())  # must not raise
