"""Unit tests for `cara.smarthome.base`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from cara.smarthome import (
    Area,
    Capability,
    Entity,
    EntityState,
    HealthStatus,
    Scene,
    SmartHomeAdapter,
    canonical_entity_id,
    parse_entity_id,
)


# --------------------------------------------------------------- canonical id


def test_canonical_entity_id_concatenates_with_colon() -> None:
    assert canonical_entity_id("ha", "light.cucina") == "ha:light.cucina"
    assert canonical_entity_id("mqtt", "bagno/luce") == "mqtt:bagno/luce"


def test_canonical_entity_id_rejects_empty_parts() -> None:
    with pytest.raises(ValueError, match="provider"):
        canonical_entity_id("", "light.cucina")
    with pytest.raises(ValueError, match="local_id"):
        canonical_entity_id("ha", "")


def test_canonical_entity_id_rejects_colon_in_provider() -> None:
    with pytest.raises(ValueError, match="must not contain"):
        canonical_entity_id("ha:nested", "light.cucina")


def test_parse_entity_id_round_trip() -> None:
    composed = canonical_entity_id("ha", "light.cucina")
    p, lid = parse_entity_id(composed)
    assert p == "ha"
    assert lid == "light.cucina"


def test_parse_entity_id_handles_local_id_with_colons_in_value() -> None:
    """parse splits on the FIRST colon — this lets MQTT topics like
    'mqtt:home:bagno/luce' round-trip."""
    p, lid = parse_entity_id("mqtt:home:bagno/luce")
    assert p == "mqtt"
    assert lid == "home:bagno/luce"


def test_parse_entity_id_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        parse_entity_id("missing-separator")
    with pytest.raises(ValueError):
        parse_entity_id(":no-provider")
    with pytest.raises(ValueError):
        parse_entity_id("no-local:")


# --------------------------------------------------------------- Capability


def test_capability_string_serialisation() -> None:
    """Capabilities are str-enum so they JSON-serialise as their value."""
    assert Capability.ON_OFF.value == "on_off"
    assert Capability.BRIGHTNESS.value == "brightness"
    # Sets of capabilities are easy to round-trip through JSON.
    json_ok = list({Capability.ON_OFF, Capability.BRIGHTNESS})
    assert all(isinstance(c.value, str) for c in json_ok)


# --------------------------------------------------------------- Entity


def test_entity_has_capability_lookup() -> None:
    e = Entity(
        id="ha:light.cucina",
        provider="homeassistant",
        domain="light",
        friendly_name="Luce cucina",
        capabilities={Capability.ON_OFF, Capability.BRIGHTNESS},
    )
    assert e.has_capability(Capability.ON_OFF)
    assert e.has_capability(Capability.BRIGHTNESS)
    assert not e.has_capability(Capability.COLOR)


def test_entity_default_visible_to_cara_true() -> None:
    e = Entity(id="ha:light.x", provider="homeassistant", domain="light",
               friendly_name="x")
    assert e.visible_to_cara is True


# --------------------------------------------------------------- protocol satisfaction


class _FakeAdapter:
    """Minimal concrete adapter; verifies the Protocol shape compiles."""
    name = "fake"
    provider = "fake"

    async def list_entities(self) -> list[Entity]:
        return []

    async def get_state(self, entity_id: str) -> EntityState | None:
        return None

    async def call_service(self, domain, service, entity_id, params=None):  # noqa: ANN001, ARG002
        return {"ok": True}

    async def list_areas(self) -> list[Area]:
        return []

    async def list_scenes(self) -> list[Scene]:
        return []

    async def health(self) -> HealthStatus:
        return HealthStatus(ok=True, provider=self.provider)

    async def subscribe_events(self) -> AsyncIterator[dict[str, Any]]:
        # async generator with no yields — closes immediately.
        if False:
            yield {}


def test_fake_adapter_satisfies_protocol() -> None:
    a = _FakeAdapter()
    assert isinstance(a, SmartHomeAdapter)


@pytest.mark.asyncio
async def test_fake_adapter_calls_round_trip() -> None:
    a = _FakeAdapter()
    assert await a.list_entities() == []
    assert await a.get_state("ha:x") is None
    out = await a.call_service("light", "turn_on", "ha:light.x")
    assert out == {"ok": True}
    h = await a.health()
    assert h.ok is True


# --------------------------------------------------------------- dataclass round-trip


def test_health_status_default_detail_empty() -> None:
    h = HealthStatus(ok=True, provider="ha")
    assert h.detail == ""
    assert h.last_event_age_s is None


def test_area_with_aliases() -> None:
    a = Area(id="cucina", name="Cucina", aliases=["kitchen", "in cucina"])
    assert "kitchen" in a.aliases
