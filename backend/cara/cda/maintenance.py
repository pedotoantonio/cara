"""Background maintenance loop for the Content Discovery Agent KB.

Runs *inside* the FastAPI process as a single asyncio task spawned at lifespan
startup. Cheap and non-invasive: walks active audio_stream items, re-checks
each via the existing `check_audio_stream` validator, and bumps success/failure
counts so the confidence score stays current.

Why no Celery: the CDA spec called for it, but Celery would be a much bigger
infrastructure addition (worker container, broker config, scheduler) for one
periodic job. An asyncio loop in the existing process is sufficient and zero
new moving parts.

Cadence is controlled by `cda_verify_interval_hours` (default 6h, 0 disables).
The loop sleeps in 60s ticks so it can react quickly to a graceful shutdown.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from sqlalchemy import select

from cara.cda.memory.content_kb import increment_failure, increment_success
from cara.cda.verification import check_audio_stream
from cara.config import settings
from cara.models.cda import CdaContentItem
from cara.store import get_sessionmaker

log = structlog.get_logger(__name__)

_task: asyncio.Task[None] | None = None
_stop = asyncio.Event()


async def _verify_once() -> tuple[int, int]:
    """One pass over active audio_stream items. Returns (ok_count, fail_count)."""
    sm = get_sessionmaker()
    ok = 0
    bad = 0
    async with sm() as session:
        rows = (
            (
                await session.execute(
                    select(CdaContentItem).where(
                        CdaContentItem.is_active.is_(True),
                        CdaContentItem.content_type == "audio_stream",
                    )
                )
            )
            .scalars()
            .all()
        )
    # We open a fresh session per item so a long pass doesn't hold one tx open
    # across all items, and a single failure doesn't roll back the rest.
    for it in rows:
        if _stop.is_set():
            break
        try:
            res = await check_audio_stream(it.url, timeout=4.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("cda.maintenance.check_error", url=it.url, error=str(exc))
            res = None
        async with sm() as session:
            try:
                if res is not None and res.ok:
                    await increment_success(session, it.id)
                    ok += 1
                else:
                    await increment_failure(session, it.id)
                    bad += 1
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                log.warning("cda.maintenance.commit_error", id=str(it.id), error=str(exc))
                await session.rollback()
        # tiny breath between items so we don't spike NPU/CPU contention
        await asyncio.sleep(0.2)
    return ok, bad


async def _loop(interval_seconds: float) -> None:
    log.info("cda.maintenance.started", interval_seconds=interval_seconds)
    next_run = time.time() + interval_seconds
    try:
        while not _stop.is_set():
            now = time.time()
            if now >= next_run:
                started = time.time()
                ok, bad = await _verify_once()
                log.info(
                    "cda.maintenance.pass_done",
                    ok=ok,
                    bad=bad,
                    elapsed_s=round(time.time() - started, 1),
                )
                next_run = time.time() + interval_seconds
            try:
                await asyncio.wait_for(_stop.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
    finally:
        log.info("cda.maintenance.stopped")


def start_maintenance() -> None:
    global _task
    interval_h = settings.cda_verify_interval_hours
    if interval_h <= 0:
        log.info("cda.maintenance.disabled", reason="cda_verify_interval_hours <= 0")
        return
    if _task is not None and not _task.done():
        return
    _stop.clear()
    _task = asyncio.create_task(_loop(interval_h * 3600), name="cda-maintenance")


async def stop_maintenance() -> None:
    global _task
    if _task is None:
        return
    _stop.set()
    try:
        await asyncio.wait_for(_task, timeout=10)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        _task.cancel()
    _task = None
