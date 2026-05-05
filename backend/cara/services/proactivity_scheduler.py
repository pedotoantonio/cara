"""Proactivity scheduler — periodic tick of the rule engine.

Every `interval_minutes` (default 10) we build a RuleContext, evaluate
the registered rules, and for each surviving Suggestion we send a Web
Push to the target user (or to every active user if `target_user_id`
is None).

This is the missing piece between `proactivity.engine` (rules + cooldown)
and `services.push` (delivery). It runs as an asyncio task spawned
from the FastAPI lifespan, alongside the push_scheduler.

Conservative design choices:
  - Imports `cara.services.proactivity.rules` lazily — registers the
    three baseline rules on first tick, exactly once per process.
  - Loads the database session per-tick so a slow rule doesn't pin a
    connection.
  - Failures of individual rules are already isolated by the engine;
    failures of the push fan-out don't block the next tick.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from cara.config import settings
from cara.services.proactivity.engine import EngineConfig, RuleContext, default_engine


log = structlog.get_logger(__name__)


# How often the engine ticks. 10 minutes balances rule freshness (e.g.
# rain alert lead time) with DB / NPU load.
DEFAULT_INTERVAL_SECONDS = 600


_rules_loaded = False


def _ensure_rules_loaded() -> None:
    """Trigger the @rule decorator side-effects in `proactivity.rules`."""
    global _rules_loaded
    if _rules_loaded:
        return
    # Import for side-effect (registration of morning_greeting,
    # undone_tasks_evening, rain_alert).
    from cara.services.proactivity import rules as _rules  # noqa: F401
    _rules_loaded = True
    log.info("proactivity.rules.loaded", ids=_rules.registered_rule_ids())


async def _push_suggestion(
    sessionmaker: async_sessionmaker,
    suggestion,
) -> int:
    """Send `suggestion` as a Web Push. Returns # of devices reached."""
    from cara.models.user import User
    from cara.services.push import PushPayload, send_to_user

    payload = PushPayload(
        title="Cara",
        body=suggestion.text,
        tag=f"proactive-{suggestion.rule_id}",
        url=(suggestion.action or {}).get("deep_link") or "/",
    )

    async with sessionmaker() as session:
        # Determine recipients: target_user_id if set, otherwise admins
        # (broad-cast to "the household").
        if suggestion.target_user_id is not None:
            return await send_to_user(
                session, user_id=suggestion.target_user_id, payload=payload,
            )

        admins = (
            await session.execute(
                select(User).where(User.is_admin.is_(True)).where(User.is_active.is_(True))
            )
        ).scalars().all()
        if not admins:
            return 0
        delivered_total = 0
        for u in admins:
            try:
                delivered_total += await send_to_user(
                    session, user_id=u.id, payload=payload,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "proactivity.push.user_failed",
                    user_id=u.id, error=str(exc),
                )
        return delivered_total


async def _tick_once(sessionmaker: async_sessionmaker) -> int:
    """One sweep: build ctx, evaluate, push suggestions. Returns # delivered."""
    _ensure_rules_loaded()

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(ZoneInfo("Europe/Rome"))

    delivered = 0
    async with sessionmaker() as session:
        ctx = RuleContext(
            now=now_local,
            db_session=session,
            # smarthome / weather adapters wired here when they have
            # service-locator access. Today they're None; rules that
            # need them gracefully short-circuit.
        )
        try:
            suggestions = await default_engine.evaluate(
                ctx, config=EngineConfig(),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("proactivity.evaluate_failed", error=str(exc))
            return 0

    if not suggestions:
        return 0

    log.info("proactivity.suggestions_fired", count=len(suggestions))
    for s in suggestions:
        try:
            n = await _push_suggestion(sessionmaker, s)
            delivered += n
            log.info(
                "proactivity.suggestion_delivered",
                rule_id=s.rule_id, devices=n, text_preview=s.text[:80],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "proactivity.suggestion_dispatch_failed",
                rule_id=s.rule_id, error=str(exc),
            )
    return delivered


async def run_loop(sessionmaker: async_sessionmaker) -> None:
    """Long-running scheduler — call once from app lifespan."""
    interval = max(60, getattr(settings, "proactivity_interval_seconds", DEFAULT_INTERVAL_SECONDS))
    log.info("proactivity_scheduler.start", interval_seconds=interval)
    try:
        while True:
            try:
                pushed = await _tick_once(sessionmaker)
                if pushed:
                    log.info("proactivity_scheduler.tick", delivered=pushed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("proactivity_scheduler.tick_error", error=str(exc))
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("proactivity_scheduler.stop")
        raise
