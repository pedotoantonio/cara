"""Shared infrastructure for `cara.agents.*` Celery tasks.

Provides `@cara_task(agent="mail", ...)` which wraps a function to:

1. Insert an `AgentRun` row in `running` state when the task starts.
2. Update it to `ok` / `failed` / `skipped` / `partial` on completion.
3. Enforce idempotency via `idempotency_key`: a re-run with the same
   key short-circuits to `skipped` if the previous run is `ok`.
4. Catch exceptions, persist the error class + message, and re-raise
   so Celery's retry policy applies.
5. Bridge the sync Celery world to our async services by spinning up
   a dedicated event loop per task. We don't share the FastAPI loop
   because Celery workers are separate processes.

Tasks declared with this decorator MUST be idempotent and bounded in
runtime. The Celery time limit (5 min hard / 4:30 soft) terminates
runaway tasks; the decorator records the timeout as a `failed` run.
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

import structlog
from celery import shared_task
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cara.config import settings
from cara.models.agent_run import (
    AGENT_STATUS_FAILED,
    AGENT_STATUS_OK,
    AGENT_STATUS_PARTIAL,
    AGENT_STATUS_RUNNING,
    AGENT_STATUS_SKIPPED,
    AgentRun,
)


log = structlog.get_logger(__name__)


# ─── Celery-side async session ──────────────────────────────────────
#
# Workers are forked processes — they cannot reuse the FastAPI engine.
# Build a dedicated engine per worker the first time a task touches
# the DB. `pool_size=2` is plenty given concurrency=1 on each worker.

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_size=2,
            max_overflow=2,
            pool_pre_ping=True,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


P = ParamSpec("P")
R = TypeVar("R")


class TaskPartialResult(Exception):
    """Raise from inside a task body to mark its run as partial — the
    task hit a soft deadline and persisted what it could."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        super().__init__("partial result")
        self.payload = payload or {}


def cara_task(
    *,
    agent: str,
    name: str | None = None,
    bind: bool = False,
    autoretry_for: tuple[type[BaseException], ...] = (),
    retry_backoff: bool = True,
    max_retries: int = 3,
) -> Callable[[Callable[P, Awaitable[Any]]], Any]:
    """Decorator: register an async function as a Celery task with the
    standard agent-run bookkeeping.

    Args:
        agent: which worker group claims this task (`mail`, `files`,
            `learn`). Drives the queue routing in `celery_app.py`.
        name: full task name. Defaults to the function's qualified name
            so beat schedules can reference it as `cara.agents.X.Y`.
        bind: classic Celery flag — if True the task receives `self`
            as its first arg.
        autoretry_for: exception classes that trigger a retry.
        retry_backoff: exponential backoff between retries.
        max_retries: hard cap on retries.

    The decorated function MUST be `async def` and accept an
    `idempotency_key: str | None` keyword argument (we read it to
    decide whether to short-circuit). All other args / kwargs pass
    through unchanged.
    """

    def decorator(fn: Callable[P, Awaitable[Any]]) -> Any:
        task_name = name or f"cara.agents.{agent}.{fn.__name__}"

        @shared_task(
            name=task_name,
            bind=bind,
            autoretry_for=autoretry_for,
            retry_backoff=retry_backoff,
            max_retries=max_retries,
        )
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return _run_in_loop(fn, agent, task_name, args, kwargs)

        return wrapper

    return decorator


def _run_in_loop(
    fn: Callable[..., Awaitable[Any]],
    agent: str,
    task_name: str,
    args: tuple,
    kwargs: dict,
) -> Any:
    """Shim: each Celery task call gets its own asyncio loop so we can
    use the async DB session. Cheap (~1 ms per task) and avoids any
    cross-task state in the loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_with_record(fn, agent, task_name, args, kwargs))
    finally:
        loop.close()


async def _run_with_record(
    fn: Callable[..., Awaitable[Any]],
    agent: str,
    task_name: str,
    args: tuple,
    kwargs: dict,
) -> Any:
    sessionmaker = _get_sessionmaker()
    idempotency_key: str | None = kwargs.get("idempotency_key")
    started_ms = time.monotonic()

    # Short-circuit if a previous run with the same key already
    # succeeded. We never duplicate side effects.
    if idempotency_key:
        async with sessionmaker() as s:
            existing = await s.execute(
                select(AgentRun).where(
                    AgentRun.agent_name == agent,
                    AgentRun.task_name == task_name,
                    AgentRun.idempotency_key == idempotency_key,
                    AgentRun.status == AGENT_STATUS_OK,
                ).limit(1)
            )
            row = existing.scalar_one_or_none()
            if row is not None:
                log.info("agent.task.skipped_idempotent",
                         agent=agent, task=task_name, key=idempotency_key)
                return {"status": AGENT_STATUS_SKIPPED, "run_id": row.id}

    # Insert running row — no commit yet; we want one row per attempt.
    async with sessionmaker() as s:
        run = AgentRun(
            agent_name=agent,
            task_name=task_name,
            idempotency_key=idempotency_key,
            status=AGENT_STATUS_RUNNING,
        )
        s.add(run)
        await s.commit()
        run_id = run.id

    status = AGENT_STATUS_OK
    payload: dict[str, Any] | None = None
    err_class: str | None = None
    err_msg: str | None = None
    result: Any = None
    try:
        result = await fn(*args, **kwargs)
        if isinstance(result, dict):
            payload = result
    except TaskPartialResult as exc:
        status = AGENT_STATUS_PARTIAL
        payload = exc.payload
    except Exception as exc:  # noqa: BLE001
        status = AGENT_STATUS_FAILED
        err_class = type(exc).__name__
        err_msg = str(exc)[:1000]
        log.warning("agent.task.failed",
                    agent=agent, task=task_name, error_class=err_class,
                    error=err_msg)
        # Re-raise so Celery's retry policy still applies.
        await _persist_finish(sessionmaker, run_id, status, payload,
                              err_class, err_msg, started_ms)
        raise

    await _persist_finish(sessionmaker, run_id, status, payload,
                          err_class, err_msg, started_ms)
    return result


async def _persist_finish(
    sessionmaker: async_sessionmaker[AsyncSession],
    run_id: int,
    status: str,
    payload: dict[str, Any] | None,
    err_class: str | None,
    err_msg: str | None,
    started_ms: float,
) -> None:
    duration_ms = int((time.monotonic() - started_ms) * 1000)
    async with sessionmaker() as s:
        await s.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(
                status=status,
                finished_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                duration_ms=duration_ms,
                payload=payload,
                error_class=err_class,
                error_message=err_msg,
            )
        )
        await s.commit()
