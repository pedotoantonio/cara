"""Unit tests for `cara.smarthome.homeassistant`. httpx mocked; no real HA."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from cara.smarthome import Capability, Entity, EntityState, HealthStatus
from cara.smarthome.homeassistant import HAConfig, HomeAssistantAdapter


pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------- helpers


def _resp(status: int, body: Any) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = body
    if status >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=r
        )
    else:
        r.raise_for_status.return_value = None
    return r


def _make_client(get_resp: MagicMock | None = None,
                 post_resp: MagicMock | None = None) -> MagicMock:
    c = MagicMock(spec=httpx.AsyncClient)
    c.get = AsyncMock(return_value=get_resp or _resp(200, []))
    c.post = AsyncMock(return_value=post_resp or _resp(200, {}))
    c.aclose = AsyncMock()
    return c


def _config() -> HAConfig:
    return HAConfig(base_url="http://localhost:8123", token="t")


# --------------------------------------------------------------- HAConfig


def test_ha_config_ws_url_derives_from_http() -> None:
    c = HAConfig(base_url="http://192.168.1.23:8123", token="t")
    assert c.ws() == "ws://192.168.1.23:8123/api/websocket"


def test_ha_config_ws_url_https_to_wss() -> None:
    c = HAConfig(base_url="https://ha.local", token="t")
    assert c.ws() == "wss://ha.local/api/websocket"


def test_ha_config_explicit_ws_url_wins() -> None:
    c = HAConfig(base_url="http://x:8123", token="t", ws_url="ws://override/ws")
    assert c.ws() == "ws://override/ws"


def test_ha_config_auth_headers() -> None:
    c = HAConfig(base_url="http://x:8123", token="abcd")
    assert c.auth_headers() == {"Authorization": "Bearer abcd"}


# --------------------------------------------------------------- list_entities


async def test_list_entities_maps_states_to_entities() -> None:
    body = [
        {"entity_id": "light.cucina", "state": "on",
         "attributes": {"friendly_name": "Luce cucina", "brightness": 200}},
        {"entity_id": "switch.tv", "state": "off",
         "attributes": {"friendly_name": "TV"}},
        {"entity_id": "sensor.temp", "state": "22.4",
         "attributes": {"friendly_name": "Temp"}},
        {"entity_id": "scene.cinema", "state": "scening",
         "attributes": {"friendly_name": "Cinema"}},
    ]
    http = _make_client(get_resp=_resp(200, body))
    a = HomeAssistantAdapter(_config(), http_client=http)

    out = await a.list_entities()
    assert len(out) == 4

    ids = [e.id for e in out]
    assert "ha:light.cucina" in ids
    assert "ha:switch.tv" in ids

    light = next(e for e in out if e.domain == "light")
    assert Capability.ON_OFF in light.capabilities
    assert Capability.BRIGHTNESS in light.capabilities  # because attribute present
    assert Capability.COLOR not in light.capabilities  # not in attrs

    switch = next(e for e in out if e.domain == "switch")
    assert switch.capabilities == {Capability.ON_OFF}

    scene = next(e for e in out if e.domain == "scene")
    assert Capability.SCENE_ACTIVATE in scene.capabilities


async def test_list_entities_uses_friendly_name_or_id_fallback() -> None:
    body = [
        {"entity_id": "light.no_name", "state": "off", "attributes": {}},
    ]
    http = _make_client(get_resp=_resp(200, body))
    a = HomeAssistantAdapter(_config(), http_client=http)
    out = await a.list_entities()
    assert out[0].friendly_name == "light.no_name"


async def test_list_entities_skips_malformed_rows() -> None:
    body = [
        {"entity_id": "light.ok", "state": "on", "attributes": {}},
        {"no_entity_id_field": True},  # malformed
    ]
    http = _make_client(get_resp=_resp(200, body))
    a = HomeAssistantAdapter(_config(), http_client=http)
    out = await a.list_entities()
    assert len(out) == 1
    assert out[0].id == "ha:light.ok"


async def test_list_entities_http_error_returns_empty() -> None:
    http = _make_client()
    http.get = AsyncMock(side_effect=httpx.RequestError("network down"))
    a = HomeAssistantAdapter(_config(), http_client=http)
    assert await a.list_entities() == []


async def test_list_entities_climate_brings_temperature_and_hvac() -> None:
    body = [{
        "entity_id": "climate.salotto",
        "state": "heat",
        "attributes": {
            "friendly_name": "Termo",
            "fan_modes": ["auto", "low"],
        },
    }]
    http = _make_client(get_resp=_resp(200, body))
    a = HomeAssistantAdapter(_config(), http_client=http)
    [c] = await a.list_entities()
    assert {Capability.TEMPERATURE, Capability.HVAC_MODE, Capability.FAN_MODE}.issubset(
        c.capabilities
    )


async def test_list_entities_cover_position_and_tilt() -> None:
    body = [{
        "entity_id": "cover.salone",
        "state": "open",
        "attributes": {
            "friendly_name": "Tapparella salone",
            "current_position": 80,
            "current_tilt_position": 30,
        },
    }]
    http = _make_client(get_resp=_resp(200, body))
    a = HomeAssistantAdapter(_config(), http_client=http)
    [c] = await a.list_entities()
    assert Capability.OPEN_CLOSE in c.capabilities
    assert Capability.POSITION in c.capabilities
    assert Capability.TILT in c.capabilities


# --------------------------------------------------------------- get_state


async def test_get_state_success() -> None:
    http = _make_client(get_resp=_resp(200, {
        "state": "on",
        "attributes": {"brightness": 150},
        "last_changed": "2026-05-04T12:00:00+00:00",
    }))
    a = HomeAssistantAdapter(_config(), http_client=http)
    s = await a.get_state("ha:light.cucina")
    assert isinstance(s, EntityState)
    assert s.state == "on"
    assert s.attributes["brightness"] == 150


async def test_get_state_404_returns_none() -> None:
    http = _make_client()
    http.get = AsyncMock(return_value=_resp(404, {}))
    a = HomeAssistantAdapter(_config(), http_client=http)
    assert await a.get_state("ha:light.missing") is None


async def test_get_state_wrong_provider_returns_none() -> None:
    http = _make_client()
    a = HomeAssistantAdapter(_config(), http_client=http)
    assert await a.get_state("mqtt:light.x") is None
    http.get.assert_not_called()


# --------------------------------------------------------------- call_service


async def test_call_service_posts_with_entity_id_in_body() -> None:
    http = _make_client(post_resp=_resp(200, {}))
    a = HomeAssistantAdapter(_config(), http_client=http)
    out = await a.call_service("light", "turn_on", "ha:light.cucina",
                               params={"brightness": 200})
    assert out["ok"] is True
    args, kwargs = http.post.call_args
    assert args[0] == "/api/services/light/turn_on"
    assert kwargs["json"]["entity_id"] == "light.cucina"
    assert kwargs["json"]["brightness"] == 200


async def test_call_service_wrong_provider_returns_error() -> None:
    http = _make_client()
    a = HomeAssistantAdapter(_config(), http_client=http)
    out = await a.call_service("light", "turn_on", "mqtt:light.x")
    assert out["ok"] is False
    http.post.assert_not_called()


async def test_call_service_http_error_returns_failure_dict() -> None:
    http = _make_client()
    http.post = AsyncMock(side_effect=httpx.RequestError("conn refused"))
    a = HomeAssistantAdapter(_config(), http_client=http)
    out = await a.call_service("light", "turn_on", "ha:light.cucina")
    assert out["ok"] is False
    assert "conn refused" in out["error"]


# --------------------------------------------------------------- list_scenes


async def test_list_scenes_filters_to_scene_domain() -> None:
    body = [
        {"entity_id": "light.x", "state": "off",
         "attributes": {"friendly_name": "X"}},
        {"entity_id": "scene.cinema", "state": "scening",
         "attributes": {"friendly_name": "Cinema",
                        "description": "Modalità cinema"}},
        {"entity_id": "scene.notte", "state": "scening",
         "attributes": {"friendly_name": "Buonanotte"}},
    ]
    http = _make_client(get_resp=_resp(200, body))
    a = HomeAssistantAdapter(_config(), http_client=http)
    scenes = await a.list_scenes()
    assert len(scenes) == 2
    names = {s.name for s in scenes}
    assert {"Cinema", "Buonanotte"} == names


# --------------------------------------------------------------- health


async def test_health_ok_when_endpoint_returns_200() -> None:
    http = _make_client(get_resp=_resp(200, {}))
    a = HomeAssistantAdapter(_config(), http_client=http)
    h = await a.health()
    assert isinstance(h, HealthStatus)
    assert h.ok is True
    assert h.provider == "ha"


async def test_health_failure_carries_detail() -> None:
    http = _make_client()
    http.get = AsyncMock(side_effect=httpx.RequestError("dns failed"))
    a = HomeAssistantAdapter(_config(), http_client=http)
    h = await a.health()
    assert h.ok is False
    assert "dns failed" in h.detail


# --------------------------------------------------------------- subscribe_events


async def test_subscribe_events_no_ws_factory_returns_empty_stream() -> None:
    a = HomeAssistantAdapter(_config(), http_client=_make_client())
    frames = [f async for f in a.subscribe_events()]
    assert frames == []


async def test_subscribe_events_yields_frames_from_factory() -> None:
    async def fake_stream():
        yield {"type": "event", "event": {"event_type": "state_changed", "data": {"x": 1}}}
        yield {"type": "event", "event": {"event_type": "automation_triggered"}}

    async def factory(_config):
        return fake_stream()

    a = HomeAssistantAdapter(_config(), http_client=_make_client(), ws_factory=factory)
    frames = [f async for f in a.subscribe_events()]
    assert len(frames) == 2
    assert frames[0]["event"]["event_type"] == "state_changed"


async def test_subscribe_events_factory_failure_yields_empty_stream() -> None:
    async def factory(_config):
        raise RuntimeError("ws connect failed")

    a = HomeAssistantAdapter(_config(), http_client=_make_client(), ws_factory=factory)
    frames = [f async for f in a.subscribe_events()]
    assert frames == []
