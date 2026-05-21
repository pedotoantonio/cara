"""Nightly persona-profile rebuild scheduler — runs in the backend process.

Lumo-conversion Ondata β.

Why in-process and not Celery (yet):

The persona_profiler needs the LLM (NPU on `cara-backend`). Celery
workers run with `LLM_ENABLED=false` because the RKLLM runtime
doesn't tolerate two handles to the same NPU. Until cara-llm HTTP
exists (Ondata δ — explicitly deferred), the only place this can
run is here in the backend, sharing the existing LLM lock.

Trade-off: the rebuild competes with chat for the NPU. We mitigate
by scheduling at 03:15 — silent hour — and by capping
`max_chunks=10` per user per run, so worst case one user takes
~3 min of NPU and the next user waits its turn.

When cara-llm HTTP arrives we move this whole module to
`cara.agents.persona` (Celery `learn` queue) without changing the
public API of `learning.persona_profiler`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from cara.ai import get_llm_service
from cara.ai.llm import LLMUnavailableError
from cara.learning import persona_profiler
from cara.models import User


log = structlog.get_logger(__name__)


# Run at 03:15 Europe/Rome — well into the silent hours window
# (22:00-07:00 per CLAUDE.md proactivity rules). 30 minutes after
# habit detection (03:00) so we don't pile up two LLM-heavy jobs.
_RUN_HOUR = 3
_RUN_MINUTE = 15

# How long to wait between user rebuilds in the same tick. Gives the
# NPU lock a chance to be picked up by chat if anyone is awake.
_INTER_USER_DELAY_S = 5.0


def _next_run_at(now: datetime) -> datetime:
    """Compute the next 03:15 timestamp ≥ now (Europe/Rome → UTC).

    We store everything in UTC so DST shifts don't drift the schedule.
    Europe/Rome 03:15 is UTC 01:15 (winter) or UTC 02:15 (summer).
    We compute in local time then convert — the zoneinfo handles DST.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Rome")
    except Exception:  # noqa: BLE001 — zoneinfo always present on py3.9+
        tz = timezone.utc

    now_local = now.astimezone(tz)
    target_today = now_local.replace(
        hour=_RUN_HOUR, minute=_RUN_MINUTE, second=0, microsecond=0
    )
    if target_today <= now_local:
        target_today = target_today + timedelta(days=1)
    return target_today.astimezone(timezone.utc)


async def _rebuild_all_users(Session: async_sessionmaker) -> None:
    """Iterate active human users and rebuild each profile."""
    llm = get_llm_service()
    if llm is None or not getattr(llm, "_loaded", False):
        log.warning("persona.scheduler.skipped",
                    reason="llm not ready")
        return

    # Pick users with at least one chat message (ignore freshly-created
    # admins who never chatted).
    async with Session() as session:
        from cara.models import Message
        users_q = (
            select(User)
            .where(User.is_active.is_(True))
            .where(
                User.id.in_(
                    select(Message.user_id).distinct().where(
                        Message.role == "user"
                    )
                )
            )
        )
        users = (await session.execute(users_q)).scalars().all()

    if not users:
        log.info("persona.scheduler.no_users")
        return

    log.info("persona.scheduler.start", n_users=len(users))

    for i, u in enumerate(users):
        try:
            async with Session() as session:
                result = await persona_profiler.rebuild_for_user(
                    session, llm, u.id
                )
                await session.commit()
            log.info("persona.scheduler.user_done",
                     user_id=u.id, idx=i + 1, total=len(users),
                     status=result.get("status"),
                     chunks=result.get("chunks_processed"),
                     confidence=result.get("confidence"))
        except LLMUnavailableError as exc:
            log.warning("persona.scheduler.llm_lost",
                        user_id=u.id, error=str(exc))
            # If we lost the NPU mid-batch, stop — the rest will run
            # next night.
            break
        except Exception as exc:  # noqa: BLE001 — never crash the scheduler
            log.exception("persona.scheduler.user_failed", user_id=u.id)
        await asyncio.sleep(_INTER_USER_DELAY_S)

    log.info("persona.scheduler.done")


async def run_loop(Session: async_sessionmaker) -> None:
    """Lifespan task — sleeps until 03:15, runs rebuild, repeats.

    Cancellation-safe: each `asyncio.sleep` honours CancelledError,
    and the rebuild itself catches all exceptions internally.
    """
    while True:
        now = datetime.now(timezone.utc)
        next_at = _next_run_at(now)
        sleep_s = max(60.0, (next_at - now).total_seconds())
        log.info(
            "persona.scheduler.sleep_until",
            next_at=next_at.isoformat(),
            sleep_seconds=int(sleep_s),
        )
        try:
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            raise

        try:
            await _rebuild_all_users(Session)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — guard the loop
            log.exception("persona.scheduler.loop_iteration_failed")
