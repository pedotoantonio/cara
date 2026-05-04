"""Weather service backed by Open-Meteo (free, no API key).

Open-Meteo is the right default for CARA: free, no key, EU-based, no
business model that depends on monetising the user's location. The
forecast API uses ECMWF + GFS internally and is easily comparable to
paid services for everyday "what's the weather like" use.

Endpoints used:
- https://api.open-meteo.com/v1/forecast (current + hourly + daily)
- https://geocoding-api.open-meteo.com/v1/search (city → lat/lon, called
  by the admin UI when a family member sets their default location)

Cache:
- current weather: 15 minutes (Redis, key = "cara:weather:current:{lat}:{lon}")
- forecast:        60 minutes (a 5-day forecast doesn't change every minute)

WMO weather code mapping is exposed as a Python dict so the frontend
icon mapping stays in sync (we serve `weather_code` and `icon_slug`
together; the slug is what `weather_icons.py` / the frontend looks up).

Wiring into the chat pipeline + Wallet widget is done in later steps.
This module just ships the typed client + cache + icon mapping so the
rest of the codebase has something to call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import structlog


log = structlog.get_logger(__name__)


_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

_DEFAULT_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
_CURRENT_TTL = 15 * 60
_FORECAST_TTL = 60 * 60


# ---------------------------------------------------------------------------
# WMO weather code → human-readable + icon slug
# ---------------------------------------------------------------------------
# Source: https://open-meteo.com/en/docs (WMO Weather interpretation codes)
# `slug` matches the icon set we ship with the frontend (Step 8.3).

WMO_CODES: dict[int, dict[str, str]] = {
    0: {"label": "Sereno", "slug": "sun"},
    1: {"label": "Prevalentemente sereno", "slug": "sun-cloud"},
    2: {"label": "Parzialmente nuvoloso", "slug": "cloud-sun"},
    3: {"label": "Coperto", "slug": "cloud"},
    45: {"label": "Nebbia", "slug": "fog"},
    48: {"label": "Nebbia con brina", "slug": "fog"},
    51: {"label": "Pioviggine leggera", "slug": "drizzle"},
    53: {"label": "Pioviggine moderata", "slug": "drizzle"},
    55: {"label": "Pioviggine intensa", "slug": "drizzle"},
    56: {"label": "Pioviggine gelata leggera", "slug": "drizzle-cold"},
    57: {"label": "Pioviggine gelata intensa", "slug": "drizzle-cold"},
    61: {"label": "Pioggia debole", "slug": "rain"},
    63: {"label": "Pioggia moderata", "slug": "rain"},
    65: {"label": "Pioggia intensa", "slug": "rain-heavy"},
    66: {"label": "Pioggia gelata", "slug": "rain-cold"},
    67: {"label": "Pioggia gelata intensa", "slug": "rain-cold"},
    71: {"label": "Neve debole", "slug": "snow"},
    73: {"label": "Neve moderata", "slug": "snow"},
    75: {"label": "Neve intensa", "slug": "snow-heavy"},
    77: {"label": "Granuli di neve", "slug": "snow"},
    80: {"label": "Rovesci leggeri", "slug": "showers"},
    81: {"label": "Rovesci moderati", "slug": "showers"},
    82: {"label": "Rovesci violenti", "slug": "showers-heavy"},
    85: {"label": "Rovesci di neve leggeri", "slug": "snow-showers"},
    86: {"label": "Rovesci di neve intensi", "slug": "snow-showers-heavy"},
    95: {"label": "Temporale", "slug": "thunderstorm"},
    96: {"label": "Temporale con grandine debole", "slug": "thunderstorm-hail"},
    99: {"label": "Temporale con grandine intensa", "slug": "thunderstorm-hail"},
}


def describe_wmo(code: int | None) -> dict[str, str]:
    """Return {'label': IT, 'slug': iconset} for a WMO code; safe fallback."""
    if code is None:
        return {"label": "Sconosciuto", "slug": "unknown"}
    return WMO_CODES.get(int(code), {"label": "Sconosciuto", "slug": "unknown"})


# ---------------------------------------------------------------------------
# Typed payloads
# ---------------------------------------------------------------------------


@dataclass
class GeocodeResult:
    name: str
    country: str
    latitude: float
    longitude: float
    timezone: str
    admin1: str | None = None  # region/state, e.g. "Lazio"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "country": self.country,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timezone": self.timezone,
            "admin1": self.admin1,
        }


@dataclass
class CurrentWeather:
    temperature_c: float
    apparent_temperature_c: float | None
    humidity: float | None
    wind_speed_kmh: float | None
    weather_code: int
    is_day: bool
    observed_at: datetime
    icon_slug: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature_c": self.temperature_c,
            "apparent_temperature_c": self.apparent_temperature_c,
            "humidity": self.humidity,
            "wind_speed_kmh": self.wind_speed_kmh,
            "weather_code": self.weather_code,
            "is_day": self.is_day,
            "observed_at": self.observed_at.isoformat(),
            "icon_slug": self.icon_slug,
            "label": self.label,
        }


@dataclass
class DailyForecast:
    date: str  # YYYY-MM-DD
    temp_min_c: float
    temp_max_c: float
    weather_code: int
    icon_slug: str
    label: str
    precipitation_mm: float
    sunrise: str | None = None
    sunset: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "temp_min_c": self.temp_min_c,
            "temp_max_c": self.temp_max_c,
            "weather_code": self.weather_code,
            "icon_slug": self.icon_slug,
            "label": self.label,
            "precipitation_mm": self.precipitation_mm,
            "sunrise": self.sunrise,
            "sunset": self.sunset,
        }


@dataclass
class WeatherBundle:
    location: GeocodeResult
    current: CurrentWeather
    daily: list[DailyForecast] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": self.location.to_dict(),
            "current": self.current.to_dict(),
            "daily": [d.to_dict() for d in self.daily],
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WeatherService:
    """Open-Meteo client with optional Redis caching.

    `redis_client` is a duck-typed redis.asyncio handle (only `get`/`set`
    are used). Pass None to disable caching — useful for tests.
    """

    def __init__(
        self,
        redis_client=None,  # noqa: ANN001
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._redis = redis_client
        self._http = http_client  # injected for tests; lazily created otherwise

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ----------------------------------------------- geocoding (admin city lookup)

    async def geocode(self, query: str, *, count: int = 5) -> list[GeocodeResult]:
        """City → list of candidate (lat, lon, name, country)."""
        if not query.strip():
            return []
        client = await self._client()
        try:
            r = await client.get(
                _GEOCODE_URL,
                params={"name": query.strip(), "count": count, "language": "it"},
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            log.warning("weather.geocode.failed", query=query, error=str(exc))
            return []

        results = []
        for item in data.get("results", []) or []:
            try:
                results.append(
                    GeocodeResult(
                        name=item["name"],
                        country=item.get("country", ""),
                        latitude=float(item["latitude"]),
                        longitude=float(item["longitude"]),
                        timezone=item.get("timezone", "auto"),
                        admin1=item.get("admin1"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    # --------------------------------------------------------------- current

    async def current(self, lat: float, lon: float, *, timezone: str = "auto") -> CurrentWeather | None:
        """Current weather at (lat, lon). Cached for 15 minutes."""
        cached = await self._cache_get(self._cur_key(lat, lon))
        if cached is not None:
            return _current_from_dict(cached)
        cur = await self._fetch_current(lat, lon, timezone=timezone)
        if cur is not None:
            await self._cache_set(self._cur_key(lat, lon), cur.to_dict(), _CURRENT_TTL)
        return cur

    async def _fetch_current(
        self, lat: float, lon: float, *, timezone: str = "auto"
    ) -> CurrentWeather | None:
        client = await self._client()
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
            "wind_speed_10m,weather_code,is_day",
            "timezone": timezone,
        }
        try:
            r = await client.get(_FORECAST_URL, params=params)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            log.warning("weather.current.failed", lat=lat, lon=lon, error=str(exc))
            return None

        cur = data.get("current") or {}
        try:
            code = int(cur.get("weather_code", 0))
            mapping = describe_wmo(code)
            return CurrentWeather(
                temperature_c=float(cur["temperature_2m"]),
                apparent_temperature_c=_safe_float(cur.get("apparent_temperature")),
                humidity=_safe_float(cur.get("relative_humidity_2m")),
                wind_speed_kmh=_safe_float(cur.get("wind_speed_10m")),
                weather_code=code,
                is_day=bool(cur.get("is_day", 1)),
                observed_at=datetime.fromisoformat(cur.get("time").replace("Z", "+00:00")),
                icon_slug=mapping["slug"],
                label=mapping["label"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("weather.current.parse_failed", error=str(exc))
            return None

    # --------------------------------------------------------------- forecast

    async def forecast(
        self,
        lat: float,
        lon: float,
        *,
        days: int = 5,
        timezone: str = "auto",
    ) -> list[DailyForecast]:
        """Daily forecast for the next `days`. Cached for 60 minutes."""
        days = max(1, min(days, 7))
        cached = await self._cache_get(self._fc_key(lat, lon, days))
        if cached is not None:
            return [_daily_from_dict(d) for d in cached]
        forecast = await self._fetch_forecast(lat, lon, days=days, timezone=timezone)
        if forecast:
            await self._cache_set(
                self._fc_key(lat, lon, days),
                [d.to_dict() for d in forecast],
                _FORECAST_TTL,
            )
        return forecast

    async def _fetch_forecast(
        self,
        lat: float,
        lon: float,
        *,
        days: int,
        timezone: str,
    ) -> list[DailyForecast]:
        client = await self._client()
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_min,temperature_2m_max,weather_code,"
            "precipitation_sum,sunrise,sunset",
            "forecast_days": days,
            "timezone": timezone,
        }
        try:
            r = await client.get(_FORECAST_URL, params=params)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            log.warning("weather.forecast.failed", lat=lat, lon=lon, error=str(exc))
            return []

        d = data.get("daily") or {}
        out: list[DailyForecast] = []
        try:
            n = len(d.get("time", []))
            for i in range(n):
                code = int(d["weather_code"][i])
                mapping = describe_wmo(code)
                out.append(
                    DailyForecast(
                        date=d["time"][i],
                        temp_min_c=float(d["temperature_2m_min"][i]),
                        temp_max_c=float(d["temperature_2m_max"][i]),
                        weather_code=code,
                        icon_slug=mapping["slug"],
                        label=mapping["label"],
                        precipitation_mm=float(d.get("precipitation_sum", [0] * n)[i]),
                        sunrise=(d.get("sunrise") or [None] * n)[i],
                        sunset=(d.get("sunset") or [None] * n)[i],
                    )
                )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            log.warning("weather.forecast.parse_failed", error=str(exc))
        return out

    # ---------------------------------------------------------- cache helpers

    @staticmethod
    def _cur_key(lat: float, lon: float) -> str:
        return f"cara:weather:current:{lat:.4f}:{lon:.4f}"

    @staticmethod
    def _fc_key(lat: float, lon: float, days: int) -> str:
        return f"cara:weather:forecast:{lat:.4f}:{lon:.4f}:{days}"

    async def _cache_get(self, key: str) -> Any:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("weather.cache.get_failed", error=str(exc))
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def _cache_set(self, key: str, value: Any, ttl: int) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception as exc:  # noqa: BLE001
            log.warning("weather.cache.set_failed", error=str(exc))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _safe_float(v) -> float | None:  # noqa: ANN001
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _current_from_dict(d: dict[str, Any]) -> CurrentWeather:
    mapping = describe_wmo(int(d.get("weather_code", 0)))
    return CurrentWeather(
        temperature_c=float(d["temperature_c"]),
        apparent_temperature_c=_safe_float(d.get("apparent_temperature_c")),
        humidity=_safe_float(d.get("humidity")),
        wind_speed_kmh=_safe_float(d.get("wind_speed_kmh")),
        weather_code=int(d["weather_code"]),
        is_day=bool(d.get("is_day", True)),
        observed_at=datetime.fromisoformat(d["observed_at"]),
        icon_slug=d.get("icon_slug", mapping["slug"]),
        label=d.get("label", mapping["label"]),
    )


def _daily_from_dict(d: dict[str, Any]) -> DailyForecast:
    mapping = describe_wmo(int(d.get("weather_code", 0)))
    return DailyForecast(
        date=d["date"],
        temp_min_c=float(d["temp_min_c"]),
        temp_max_c=float(d["temp_max_c"]),
        weather_code=int(d["weather_code"]),
        icon_slug=d.get("icon_slug", mapping["slug"]),
        label=d.get("label", mapping["label"]),
        precipitation_mm=float(d.get("precipitation_mm", 0.0)),
        sunrise=d.get("sunrise"),
        sunset=d.get("sunset"),
    )
