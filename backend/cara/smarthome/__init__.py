"""Smart home abstraction layer.

CARA doesn't talk directly to Home Assistant or to MQTT. It talks to a
generic `SmartHomeAdapter` interface; HA is just the first concrete
implementation. KNX, Zigbee2MQTT, Shelly Cloud are future adapters that
implement the same Protocol.

The user-visible benefit: switching backends doesn't break the chat
pipeline, the proactivity rules, or the admin UI.
"""

from cara.smarthome.base import (
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
from cara.smarthome.homeassistant import HAConfig, HomeAssistantAdapter

__all__ = [
    "Area",
    "Capability",
    "Entity",
    "EntityState",
    "HAConfig",
    "HealthStatus",
    "HomeAssistantAdapter",
    "Scene",
    "SmartHomeAdapter",
    "canonical_entity_id",
    "parse_entity_id",
]
