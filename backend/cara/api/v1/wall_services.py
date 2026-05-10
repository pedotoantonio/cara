"""`/api/v1/wall/services*` — service status board for the CARA Wall.

Lists every CARA-related Docker container with state + health, and lets
the LAN user start/stop/restart them. Reuses the LAN-only access guard
from `wall.py` so the same trust boundary applies.

The service catalogue is intentionally hard-coded (vs. discovered) so
the UI can render even when a container is *missing* (e.g. crashed and
removed) and so we always know the human-readable name + role per
service. Keep it in sync with `docker-compose.yml`.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.v1.wall import require_lan
from cara.services import admin_settings as admin_svc
from cara.services import docker_client as dc
from cara.store.db import get_session

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/wall", tags=["wall"])


# ─── Service catalogue ───────────────────────────────────────────────
# `role`:
#   "stateless" — safe to restart/recreate freely (no local data loss)
#   "stateful"  — has local volume w/ data; restart OK, replace risky
# `category` is just a UI grouping hint.

CATALOG: list[dict[str, str]] = [
    # ── Core app (stateless, restart-safe) ───────────────────────────
    {"name": "cara-backend", "label": "Backend API",
     "category": "Core", "role": "stateless"},
    {"name": "cara-frontend", "label": "Frontend (nginx)",
     "category": "Core", "role": "stateless"},
    # ── Celery agents (stateless workers) ────────────────────────────
    {"name": "cara-celery-beat", "label": "Celery beat (scheduler)",
     "category": "Agenti", "role": "stateless"},
    {"name": "cara-celery-mail", "label": "Celery mail (Gmail/Calendar)",
     "category": "Agenti", "role": "stateless"},
    {"name": "cara-celery-files", "label": "Celery files (PDF/OCR)",
     "category": "Agenti", "role": "stateless"},
    {"name": "cara-celery-learn", "label": "Celery learn (habits/reflective)",
     "category": "Agenti", "role": "stateless"},
    {"name": "cara-celery-presence", "label": "Celery presence (volti)",
     "category": "Agenti", "role": "stateless"},
    # ── Stateful infra (restart OK, replace = data loss risk) ────────
    {"name": "cara-postgres", "label": "PostgreSQL",
     "category": "Infra", "role": "stateful"},
    {"name": "cara-redis", "label": "Redis",
     "category": "Infra", "role": "stateful"},
    {"name": "cara-minio", "label": "MinIO (object storage)",
     "category": "Infra", "role": "stateful"},
    {"name": "cara-chroma", "label": "ChromaDB (vector)",
     "category": "Infra", "role": "stateful"},
    # ── Adjacent services CARA depends on ────────────────────────────
    {"name": "frigate-faces", "label": "Frigate Faces (riconoscimento)",
     "category": "Adiacenti", "role": "stateful"},
    {"name": "frigate", "label": "Frigate NVR",
     "category": "Adiacenti", "role": "stateful"},
    {"name": "nginx-proxy", "label": "Reverse proxy",
     "category": "Adiacenti", "role": "stateless"},
]

_VALID_NAMES: set[str] = {s["name"] for s in CATALOG}


# ─── Endpoints ───────────────────────────────────────────────────────


@router.get("/services")
async def list_services(
    _lan: None = Depends(require_lan),  # noqa: B008
) -> dict[str, Any]:
    """Snapshot of every catalogued service: state, health, uptime,
    resource usage. Designed for 5-second polling from the Wall page."""
    if not dc.is_socket_available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Docker socket non montato sul backend",
        )

    items: list[dict[str, Any]] = []
    for entry in CATALOG:
        name = entry["name"]
        try:
            insp = await dc.inspect_container(name)
        except httpx.HTTPError as exc:
            log.warning("docker.inspect_failed", name=name, error=str(exc))
            insp = None

        state = (insp or {}).get("State", {}) or {}
        items.append({
            "name": name,
            "label": entry["label"],
            "category": entry["category"],
            "role": entry["role"],
            "exists": insp is not None,
            "color": dc.state_color(insp),
            "status": dc.short_status(insp),
            "running": bool(state.get("Running")),
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            "exit_code": state.get("ExitCode"),
            "restart_count": (insp or {}).get("RestartCount", 0),
            "image": (insp or {}).get("Config", {}).get("Image"),
        })

    summary = {
        "green": sum(1 for i in items if i["color"] == "green"),
        "yellow": sum(1 for i in items if i["color"] == "yellow"),
        "red": sum(1 for i in items if i["color"] == "red"),
        "gray": sum(1 for i in items if i["color"] == "gray"),
    }
    return {"items": items, "summary": summary}


@router.get("/services/health")
async def services_health(
    _lan: None = Depends(require_lan),  # noqa: B008
) -> dict[str, Any]:
    """Snapshot of every functional probe maintained by
    `cara.agents.health.tick`. Results live in Redis (5 min TTL of
    freshness; 1 day TTL of presence)."""
    from cara.agents import health as _health  # noqa: PLC0415
    return await _health.read_snapshot()


@router.post("/services/health/run")
async def services_health_run_now(
    _lan: None = Depends(require_lan),  # noqa: B008
) -> dict[str, Any]:
    """Force a health pass on demand (synchronously) — useful right
    after a fix to confirm the probe is green again, without waiting
    5 minutes for the next beat fire."""
    from cara.agents import health as _health  # noqa: PLC0415
    try:
        await _health.run_probes_once()
    except Exception as exc:  # noqa: BLE001
        log.warning("wall.health.run_failed", error=str(exc))
    return await _health.read_snapshot()


@router.post("/services/{name}/{action}")
async def service_action(
    name: str,
    action: str,
    _lan: None = Depends(require_lan),  # noqa: B008
) -> dict[str, Any]:
    """Start / stop / restart a catalogued container.

    NOTE: this catch-all `/services/{name}/{action}` would shadow any
    other 2-segment POST under `/services/`. The specific routes
    (e.g. `/services/health/run`) MUST be registered before this one
    in the file so FastAPI matches them first."""
    if name not in _VALID_NAMES:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Servizio sconosciuto: {name}",
        )
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Azione non supportata: {action}",
        )
    if not dc.is_socket_available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Docker socket non montato sul backend",
        )

    try:
        await dc.container_action(name, action)
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:200] if exc.response is not None else ""
        log.warning("wall.services.action_failed",
                    name=name, action=action, status=exc.response.status_code,
                    body=body)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Docker rifiuta {action}({name}): {body or exc}",
        ) from exc
    except httpx.HTTPError as exc:
        log.warning("wall.services.action_network_failed",
                    name=name, action=action, error=str(exc))
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Errore di rete verso Docker: {exc}",
        ) from exc

    log.info("wall.services.action", name=name, action=action)
    insp = await dc.inspect_container(name)
    return {
        "name": name,
        "action": action,
        "ok": True,
        "color": dc.state_color(insp),
        "status": dc.short_status(insp),
    }


@router.get("/services/watchdog")
async def watchdog_status(
    _lan: None = Depends(require_lan),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    return {
        "enabled": bool(await admin_svc.get(session, "wall_watchdog_enabled")),
        "min_bad_ticks": int(
            await admin_svc.get(session, "wall_watchdog_min_bad_ticks") or 2
        ),
        "escalate_bad_ticks": int(
            await admin_svc.get(session, "wall_watchdog_escalate_bad_ticks") or 6
        ),
    }


@router.post("/services/watchdog")
async def watchdog_toggle(
    payload: dict[str, Any] = Body(...),  # noqa: B008
    _lan: None = Depends(require_lan),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", False))
    await admin_svc.set(session, "wall_watchdog_enabled", enabled, actor_user_id=None)
    await session.commit()
    log.info("wall.services.watchdog_toggled", enabled=enabled)
    return {"enabled": enabled}


__all__ = ["router", "CATALOG"]
