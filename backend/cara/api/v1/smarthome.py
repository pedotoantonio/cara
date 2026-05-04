"""Smart-home endpoints — read entities + invoke services through the
configured `SmartHomeAdapter` (currently HomeAssistant only).

  GET    /api/v1/smarthome/entities                    list discovered entities
  GET    /api/v1/smarthome/entities/{id}/state         single state snapshot
  POST   /api/v1/smarthome/services                    invoke a service (gated by perms)
  GET    /api/v1/smarthome/scenes                      list scenes
  GET    /api/v1/smarthome/health                      adapter health snapshot
  POST   /api/v1/smarthome/resolve                     NLU: utterance → entity + action

Operations that change state run through `check_permission()` first
(Step 5.8). The user role + their explicit DevicePermission rows decide
allow/deny/ask. ASK responses are surfaced as 200 + `requires_confirmation`
so the UI can prompt and POST again with `confirmed=true`.

Adapter is configured via admin_settings (`smarthome.ha_url`,
`smarthome.ha_token`); this module reads those at request time so a
config update doesn't need a restart.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.device_permission import (
    ACTION_ALARM,
    ACTION_CONTROL,
    ACTION_LOCK,
    ACTION_QUERY,
    PERM_ALLOW,
    PERM_ASK,
    PERM_DENY,
)
from cara.models.user import User
from cara.services import admin_settings as admin_settings_svc
from cara.services.smarthome_permissions import check_permission
from cara.smarthome import (
    Capability,
    HAConfig,
    HomeAssistantAdapter,
    SmartHomeAdapter,
)
from cara.smarthome.nlu import (
    Action,
    SmartHomeNLU,
    aliases_from_entities,
)
from cara.store import get_session


router = APIRouter(prefix="/smarthome", tags=["smarthome"])


# ---------------------------------------------------------------------------
# Adapter resolution (cached per-process; rebuilt on settings change)
# ---------------------------------------------------------------------------


_adapter: SmartHomeAdapter | None = None
_adapter_signature: tuple[str, str] | None = None


async def _resolve_adapter(session: AsyncSession) -> SmartHomeAdapter | None:
    """Return the configured adapter (HA only for now). None if disabled."""
    global _adapter, _adapter_signature

    enabled = await admin_settings_svc.get(session, "smarthome.enabled")
    if not enabled:
        return None
    url = await admin_settings_svc.get(session, "smarthome.ha_url")
    token = await admin_settings_svc.get(session, "smarthome.ha_token")
    if not url or not token:
        return None

    sig = (str(url), str(token)[:8])  # token short prefix is enough to detect rotations
    if _adapter is not None and _adapter_signature == sig:
        return _adapter
    # Replace.
    if _adapter is not None:
        try:
            await _adapter.aclose()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    _adapter = HomeAssistantAdapter(HAConfig(base_url=str(url), token=str(token)))
    _adapter_signature = sig
    return _adapter


def _no_adapter() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "smart-home adapter not configured",
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CallServiceRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=40)
    service: str = Field(min_length=1, max_length=40)
    entity_id: str = Field(min_length=3, max_length=120)
    params: dict[str, Any] | None = None
    confirmed: bool = False  # set by the UI after the user OKs an ASK prompt


class ResolveRequest(BaseModel):
    utterance: str = Field(min_length=1, max_length=500)
    present_in_area: str | None = Field(default=None, max_length=80)


# ---------------------------------------------------------------------------
# Entity / state / scenes
# ---------------------------------------------------------------------------


def _entity_to_dict(e) -> dict[str, Any]:  # noqa: ANN001
    return {
        "id": e.id,
        "provider": e.provider,
        "domain": e.domain,
        "friendly_name": e.friendly_name,
        "area": e.area,
        "state": e.state,
        "capabilities": sorted(c.value for c in e.capabilities),
        "visible_to_cara": e.visible_to_cara,
    }


@router.get("/entities")
async def list_entities(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """List entities (cached server-side by the adapter)."""
    adapter = await _resolve_adapter(session)
    if adapter is None:
        raise _no_adapter()
    entities = await adapter.list_entities()
    return {
        "provider": adapter.provider,
        "count": len(entities),
        "items": [_entity_to_dict(e) for e in entities],
    }


@router.get("/entities/{entity_id:path}/state")
async def get_entity_state(
    entity_id: str,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    adapter = await _resolve_adapter(session)
    if adapter is None:
        raise _no_adapter()

    perm = await check_permission(
        session,
        user_id=user.id, user_role=user.role or "guest",
        entity_id=entity_id, action=ACTION_QUERY,
    )
    if perm.decision == PERM_DENY:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "permission denied")

    snap = await adapter.get_state(entity_id)
    if snap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entity not found")
    return {
        "entity_id": snap.entity_id,
        "state": snap.state,
        "attributes": snap.attributes,
        "last_changed": snap.last_changed,
    }


@router.get("/scenes")
async def list_scenes(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    adapter = await _resolve_adapter(session)
    if adapter is None:
        raise _no_adapter()
    scenes = await adapter.list_scenes()
    return {
        "provider": adapter.provider,
        "count": len(scenes),
        "items": [
            {"id": s.id, "name": s.name, "description": s.description}
            for s in scenes
        ],
    }


@router.get("/health")
async def health(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    adapter = await _resolve_adapter(session)
    if adapter is None:
        return {"ok": False, "provider": None, "detail": "not configured"}
    h = await adapter.health()
    return {
        "ok": h.ok, "provider": h.provider, "detail": h.detail,
        "last_event_age_s": h.last_event_age_s,
    }


# ---------------------------------------------------------------------------
# call_service — gated by permissions
# ---------------------------------------------------------------------------


def _action_for_request(req: CallServiceRequest) -> str:
    """Map a service call to the action axis the permissions matrix uses."""
    domain = req.domain.lower()
    service = req.service.lower()
    if domain == "lock":
        return ACTION_LOCK
    if domain == "alarm_control_panel":
        return ACTION_ALARM
    # Reads (state queries) go through GET endpoints; everything that
    # arrives via POST is treated as control.
    return ACTION_CONTROL


@router.post("/services")
async def call_service(
    body: CallServiceRequest,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    adapter = await _resolve_adapter(session)
    if adapter is None:
        raise _no_adapter()

    action_axis = _action_for_request(body)
    perm = await check_permission(
        session,
        user_id=user.id, user_role=user.role or "guest",
        entity_id=body.entity_id, action=action_axis,
    )
    if perm.decision == PERM_DENY:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"permission denied for {body.entity_id} ({perm.matched_source})",
        )
    if perm.decision == PERM_ASK and not body.confirmed:
        return {
            "executed": False,
            "requires_confirmation": True,
            "matched_pattern": perm.matched_pattern,
            "reason": perm.reason or "azione critica — conferma richiesta",
        }

    result = await adapter.call_service(
        body.domain, body.service, body.entity_id, body.params,
    )
    return {
        "executed": bool(result.get("ok")),
        "requires_confirmation": False,
        "result": result,
        "permission": perm.decision,
        "permission_source": perm.matched_source,
    }


# ---------------------------------------------------------------------------
# NLU resolve
# ---------------------------------------------------------------------------


@router.post("/resolve")
async def resolve_utterance(
    body: ResolveRequest,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Resolve a natural-language utterance to (action, entity, value).

    Useful for the Wall touchscreen "voice mapping test" admin tool and
    as a debugging endpoint. The chat layer will call the same NLU
    in-process once Step 0.2 lands.
    """
    adapter = await _resolve_adapter(session)
    if adapter is None:
        raise _no_adapter()
    entities = await adapter.list_entities()
    nlu = SmartHomeNLU(aliases_from_entities(entities))
    res = await nlu.resolve(body.utterance, present_in_area=body.present_in_area)
    return {
        "matched_intent": res.matched_intent,
        "action": res.action.value if res.action else None,
        "target_phrase": res.target_phrase,
        "value": res.value,
        "confidence": res.confidence,
        "needs_clarification": res.needs_clarification,
        "reason": res.reason,
        "candidates": [
            {
                "entity_id": c.entity_id, "alias": c.alias,
                "score": c.score, "source": c.source, "area": c.area,
            }
            for c in res.candidates
        ],
    }
