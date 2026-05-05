"""Admin endpoints for the proactivity engine.

  GET   /api/v1/admin/proactivity/rules          (list with metadata)
  POST  /api/v1/admin/proactivity/rules/{id}/toggle?enabled=true
  POST  /api/v1/admin/proactivity/run-now        (force a one-shot tick)

The toggle persists into the in-memory registry. There's no DB schema
for per-rule state yet — for now toggles reset on backend restart,
which is acceptable for a household-scale install. Promote to a
`proactivity_rule_state` table when the rules count grows past ~20.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from cara.api.deps import require_admin
from cara.models.user import User
from cara.services.proactivity.engine import (
    EngineConfig,
    RuleContext,
    default_engine,
    registry,
)
from cara.store import get_session


log = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/proactivity", tags=["admin", "proactivity"])


@router.get("/rules")
async def list_rules(
    _admin: User = Depends(require_admin),  # noqa: B008
) -> list[dict]:
    """All registered rules + their current enabled / cooldown state."""
    # Make sure the rules module has imported (registers @rule decorators).
    try:
        from cara.services.proactivity import rules as _rules  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        log.warning("proactivity.rules_import_failed", error=str(exc))

    out = []
    for entry in registry.all():
        out.append({
            "rule_id": entry.rule_id,
            "description": entry.description,
            "enabled": entry.enabled,
            "cooldown_hours": entry.cooldown_hours,
            "last_fired_at": entry.last_fired_at.isoformat() if entry.last_fired_at else None,
        })
    return out


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(
    rule_id: str,
    enabled: bool = Query(..., description="True to enable, False to disable."),
    _admin: User = Depends(require_admin),  # noqa: B008
) -> dict:
    """Flip a rule's enabled flag. Reset on backend restart."""
    ok = registry.set_enabled(rule_id, enabled)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown rule: {rule_id}")
    log.info("proactivity.rule_toggled", rule_id=rule_id, enabled=enabled)
    return {"rule_id": rule_id, "enabled": enabled}


@router.post("/run-now")
async def run_now(
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Force a one-shot evaluate. Useful for "did the rule actually fire?".

    Bypasses the silent-hours window and the cooldown reset. Returns the
    list of suggestions that WOULD have been emitted right now.
    """
    try:
        from cara.services.proactivity import rules as _rules  # noqa: F401
    except Exception:  # noqa: BLE001
        pass

    now_local = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
    ctx = RuleContext(now=now_local, db_session=session)
    cfg = EngineConfig()
    suggestions = await default_engine.evaluate(ctx, config=cfg)
    return {
        "suggestions": [
            {
                "rule_id": s.rule_id,
                "text": s.text,
                "priority": int(s.priority),
                "target_user_id": s.target_user_id,
                "action": s.action,
            }
            for s in suggestions
        ],
        "count": len(suggestions),
    }
