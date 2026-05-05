"""SmartHomeAdapter Protocol + canonical types.

`Entity.id` is canonical: `<provider>:<domain>.<local_id>`, e.g.
`ha:light.cucina`, `mqtt:bagno/luce`. The prefix prevents two providers
from colliding on identical local IDs.

All adapter methods are async because every plausible backend (HA REST,
HA WebSocket, MQTT, REST APIs) is async over the wire. Synchronous
methods are intentionally absent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Capabilities — the cross-vendor vocabulary CARA's NLU works with
# ---------------------------------------------------------------------------


class Capability(str, Enum):
    """What a device can do, normalised across providers."""

    ON_OFF = "on_off"
    BRIGHTNESS = "brightness"      # 0..100
    COLOR = "color"                 # RGB / hex
    COLOR_TEMP = "color_temp"       # warm/cool
    TEMPERATURE = "temperature"     # set-point
    HVAC_MODE = "hvac_mode"
    FAN_MODE = "fan_mode"
    OPEN_CLOSE = "open_close"
    POSITION = "position"           # 0..100 for covers
    TILT = "tilt"
    LOCK_UNLOCK = "lock_unlock"
    PLAY_PAUSE = "play_pause"
    VOLUME = "volume"
    SOURCE = "source"
    SCENE_ACTIVATE = "scene_activate"
    SCRIPT_RUN = "script_run"
    AUTOMATION_TRIGGER = "automation_trigger"


# ---------------------------------------------------------------------------
# Canonical entity id
# ---------------------------------------------------------------------------


def canonical_entity_id(provider: str, local_id: str) -> str:
    """Compose a canonical id: `<provider>:<local_id>`.

    No validation of `local_id` shape — that's HA-specific (`light.cucina`)
    or MQTT-specific (`bagno/luce`) and we don't impose either.
    """
    if not provider:
        raise ValueError("provider is required")
    if not local_id:
        raise ValueError("local_id is required")
    if ":" in provider:
        raise ValueError("provider must not contain ':'")
    return f"{provider}:{local_id}"


def parse_entity_id(canonical_id: str) -> tuple[str, str]:
    """Split a canonical id back into (provider, local_id)."""
    if ":" not in canonical_id:
        raise ValueError(f"not a canonical entity id: {canonical_id!r}")
    provider, _, local_id = canonical_id.partition(":")
    if not provider or not local_id:
        raise ValueError(f"malformed entity id: {canonical_id!r}")
    return provider, local_id


# ---------------------------------------------------------------------------
# Entities, areas, scenes
# ---------------------------------------------------------------------------


@dataclass
class Entity:
    """A controllable device or readable sensor."""

    id: str                                     # canonical, e.g. "ha:light.cucina"
    provider: str                               # "homeassistant" | "mqtt" | …
    domain: str                                 # "light" | "switch" | "sensor" | …
    friendly_name: str
    area: str | None = None
    state: Any = None
    attributes: dict[str, Any] = field(default_factory=dict)
    capabilities: set[Capability] = field(default_factory=set)
    visible_to_cara: bool = True

    def has_capability(self, cap: Capability) -> bool:
        return cap in self.capabilities


@dataclass
class EntityState:
    """A snapshot of one entity's state at a point in time."""

    entity_id: str
    state: Any
    attributes: dict[str, Any] = field(default_factory=dict)
    last_changed: str | None = None             # ISO timestamp (provider's)


@dataclass
class Area:
    """A room or zone the user can refer to ('cucina', 'soggiorno')."""

    id: str
    name: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class Scene:
    """A pre-set arrangement of multiple entity states ('modalità cinema')."""

    id: str
    name: str
    description: str | None = None


@dataclass
class HealthStatus:
    """Adapter health snapshot for the admin dashboard."""

    ok: bool
    provider: str
    detail: str = ""
    last_event_age_s: float | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


# Event handler shape: receives a dict with at least `entity_id`, `state`,
# and `provider`. Concrete adapters add more fields freely.
EventHandler = Callable[[dict[str, Any]], Any]


@runtime_checkable
class SmartHomeAdapter(Protocol):
    """The contract every backend (HA, MQTT, KNX, ...) implements."""

    name: str
    provider: str  # short slug used as the prefix in canonical entity ids

    async def list_entities(self) -> list[Entity]: ...
    async def get_state(self, entity_id: str) -> EntityState | None: ...
    async def call_service(
        self, domain: str, service: str, entity_id: str, params: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    async def list_areas(self) -> list[Area]: ...
    async def list_scenes(self) -> list[Scene]: ...
    async def health(self) -> HealthStatus: ...

    # Streaming: yields each event as soon as it arrives. Subclasses MAY
    # raise StopAsyncIteration to indicate the stream is closed and the
    # caller should reconnect.
    def subscribe_events(self) -> AsyncIterator[dict[str, Any]]: ...
