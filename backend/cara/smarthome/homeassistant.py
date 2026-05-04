"""Home Assistant adapter (REST + WebSocket).

Implements `SmartHomeAdapter` against a running Home Assistant instance.
HA on this NanoPC is the host-mode container at `http://172.31.0.1:8123`
(see CLAUDE.md), authenticated with a Long-Lived Access Token the admin
configures in the UI.

Responsibilities:

- **Discovery via REST**: `GET /api/states`, `GET /api/config` →
  populate the `Entity` / `Area` cache. HA sends one row per "thing"
  (light, sensor, person, automation, …) — we map the domain to
  capabilities the rest of CARA understands.
- **State queries via REST**: cheap and idempotent.
- **Service calls via REST**: turn_on / turn_off / set / scene.activate
  → `POST /api/services/<domain>/<service>`.
- **Real-time events via WebSocket**: `state_changed`, `automation_*`,
  `call_service`. Pushed into an async iterator the caller consumes.

The WS subscription path uses HA's auth-via-message handshake (auth →
subscribe_events → result/event frames). All errors at the WS level
degrade to "reconnect later"; no exceptions propagate.

Tests pass `http_client=` and `ws_factory=` injection points so we can
assert behaviour without ever opening a socket.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from cara.smarthome.base import (
    Area,
    Capability,
    Entity,
    EntityState,
    HealthStatus,
    Scene,
    canonical_entity_id,
    parse_entity_id,
)


log = structlog.get_logger(__name__)


_DEFAULT_TIMEOUT = httpx.Timeout(8.0, connect=4.0)


# ---------------------------------------------------------------------------
# Domain → capability mapping
# ---------------------------------------------------------------------------


def _capabilities_for_state(domain: str, attributes: dict[str, Any]) -> set[Capability]:
    """Heuristic mapping HA domain + attributes → CARA capabilities.

    Conservative: include a capability only if HA's attributes confirm
    the device actually supports it. Example: a `light` may or may not
    support `brightness` — we only declare the capability when the
    attribute is present.
    """
    caps: set[Capability] = set()
    if domain in {"light", "switch", "fan", "media_player", "input_boolean"}:
        caps.add(Capability.ON_OFF)
    if domain == "light":
        if "brightness" in attributes:
            caps.add(Capability.BRIGHTNESS)
        if "rgb_color" in attributes or "hs_color" in attributes:
            caps.add(Capability.COLOR)
        if "color_temp" in attributes:
            caps.add(Capability.COLOR_TEMP)
    if domain == "climate":
        caps.update({Capability.TEMPERATURE, Capability.HVAC_MODE})
        if "fan_modes" in attributes:
            caps.add(Capability.FAN_MODE)
    if domain == "cover":
        caps.add(Capability.OPEN_CLOSE)
        if "current_position" in attributes:
            caps.add(Capability.POSITION)
        if "current_tilt_position" in attributes:
            caps.add(Capability.TILT)
    if domain == "lock":
        caps.add(Capability.LOCK_UNLOCK)
    if domain == "media_player":
        caps.update({Capability.PLAY_PAUSE, Capability.VOLUME, Capability.SOURCE})
    if domain == "scene":
        caps.add(Capability.SCENE_ACTIVATE)
    if domain == "script":
        caps.add(Capability.SCRIPT_RUN)
    if domain == "automation":
        caps.add(Capability.AUTOMATION_TRIGGER)
    return caps


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class HAConfig:
    base_url: str
    token: str
    ws_url: str | None = None  # default derived from base_url
    timeout_seconds: float = 8.0

    def ws(self) -> str:
        if self.ws_url:
            return self.ws_url
        return self.base_url.rstrip("/").replace("http://", "ws://").replace(
            "https://", "wss://"
        ) + "/api/websocket"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


# Type for the optional websocket factory injected in tests. The factory
# is called once per `subscribe_events` invocation and returns an async
# iterator yielding decoded JSON frames; production wires this to
# httpx-ws or websockets, but tests can return a list-based fake.
WsFactory = Callable[[HAConfig], Awaitable[AsyncIterator[dict[str, Any]]]]


class HomeAssistantAdapter:
    """Concrete `SmartHomeAdapter` against the HA REST + WS APIs."""

    name = "homeassistant"
    provider = "ha"

    def __init__(
        self,
        config: HAConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        ws_factory: WsFactory | None = None,
    ) -> None:
        self._config = config
        self._http = http_client
        self._ws_factory = ws_factory
        self._last_event_at: float | None = None

    # ----------------------------------------------------------- http helpers

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._config.base_url,
                timeout=httpx.Timeout(self._config.timeout_seconds, connect=4.0),
                headers=self._config.auth_headers(),
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ---------------------------------------------------------- public methods

    async def list_entities(self) -> list[Entity]:
        client = await self._client()
        try:
            r = await client.get("/api/states")
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            log.warning("ha.list_entities.failed", error=str(exc))
            return []

        entities: list[Entity] = []
        for row in data:
            try:
                local_id = row["entity_id"]
                domain, _, _ = local_id.partition(".")
                attributes = row.get("attributes", {}) or {}
                friendly = attributes.get("friendly_name", local_id)
                area = attributes.get("area_id") or attributes.get("area")
                entities.append(
                    Entity(
                        id=canonical_entity_id(self.provider, local_id),
                        provider=self.name,
                        domain=domain,
                        friendly_name=str(friendly),
                        area=area,
                        state=row.get("state"),
                        attributes=attributes,
                        capabilities=_capabilities_for_state(domain, attributes),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return entities

    async def get_state(self, entity_id: str) -> EntityState | None:
        provider, local_id = parse_entity_id(entity_id)
        if provider != self.provider:
            return None
        client = await self._client()
        try:
            r = await client.get(f"/api/states/{local_id}")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            row = r.json()
        except httpx.HTTPError as exc:
            log.warning("ha.get_state.failed", entity=entity_id, error=str(exc))
            return None
        return EntityState(
            entity_id=entity_id,
            state=row.get("state"),
            attributes=row.get("attributes", {}) or {},
            last_changed=row.get("last_changed"),
        )

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider, local_id = parse_entity_id(entity_id)
        if provider != self.provider:
            return {"ok": False, "error": f"wrong provider: {provider}"}
        body: dict[str, Any] = {"entity_id": local_id}
        if params:
            body.update(params)
        client = await self._client()
        try:
            r = await client.post(f"/api/services/{domain}/{service}", json=body)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning(
                "ha.call_service.failed",
                domain=domain, service=service, entity=entity_id, error=str(exc),
            )
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "domain": domain, "service": service, "entity_id": entity_id}

    async def list_areas(self) -> list[Area]:
        """HA exposes areas via the WebSocket API only — this REST stub
        returns an empty list. The proper area listing comes from
        `subscribe_events`+ `config/area_registry/list` in a future
        iteration. For now `Entity.area` is enough for the chat NLU.
        """
        return []

    async def list_scenes(self) -> list[Scene]:
        """Scenes are entities with domain='scene' — derive from the
        states endpoint instead of asking for them separately."""
        scenes: list[Scene] = []
        for e in await self.list_entities():
            if e.domain == "scene":
                scenes.append(
                    Scene(
                        id=e.id,
                        name=e.friendly_name,
                        description=e.attributes.get("description"),
                    )
                )
        return scenes

    async def health(self) -> HealthStatus:
        """Hit `/api/` (HA's auth-required ping endpoint)."""
        client = await self._client()
        try:
            r = await client.get("/api/")
            ok = r.status_code == 200
        except httpx.HTTPError as exc:
            return HealthStatus(ok=False, provider=self.provider, detail=str(exc))
        last_age = None
        if self._last_event_at is not None:
            last_age = max(0.0, asyncio.get_event_loop().time() - self._last_event_at)
        return HealthStatus(
            ok=ok,
            provider=self.provider,
            detail="ok" if ok else f"http {r.status_code}",
            last_event_age_s=last_age,
        )

    async def subscribe_events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield decoded event payloads as they arrive from HA's WS API.

        Production: opens a WebSocket, performs the `auth → subscribe`
        handshake, yields each `event` frame as a dict.

        Tests: pass `ws_factory=` to inject a fake stream of frames.

        Errors are LOGGED, not raised — the caller is expected to
        reconnect by calling subscribe_events() again on demand.
        """
        if self._ws_factory is None:
            log.warning("ha.subscribe_events.no_ws_factory")
            return
            yield  # pragma: no cover — make this an async generator

        try:
            stream = await self._ws_factory(self._config)
        except Exception as exc:  # noqa: BLE001
            log.warning("ha.subscribe_events.connect_failed", error=str(exc))
            return
            yield  # pragma: no cover

        async for frame in stream:
            self._last_event_at = asyncio.get_event_loop().time()
            yield frame
