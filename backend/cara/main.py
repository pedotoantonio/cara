"""CARA backend entrypoint."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from cara import __version__
from cara.ai.llm import LLMUnavailableError, init_llm_service, shutdown_llm_service
from cara.ai.tts import init_tts_service, shutdown_tts_service
from cara.api.v1 import router as api_v1_router
from cara.cda.maintenance import start_maintenance, stop_maintenance
from cara.cda.rate_limit import attach_redis_url as cda_attach_redis_url
from cara.skills import primitives as _skill_primitives  # noqa: F401 — register @primitive
from cara.config import settings
from cara.core import get_state_machine
from cara.integrations import google_oauth as _google_oauth
from cara.integrations.telegram import start_telegram_bot, stop_telegram_bot
from cara.services.integrations.calendar_sync import run_loop as calendar_sync_loop
from cara.services.integrations.gmail_scanner import run_loop as gmail_scanner_loop
from cara.services.proactivity_scheduler import run_loop as proactivity_scheduler_loop
from cara.services.push import is_configured as push_is_configured
from cara.services.push_scheduler import run_loop as push_scheduler_loop
from cara.services.smarthome_events import run_loop as ha_events_loop
from cara.store import get_sessionmaker, init_engine, shutdown_engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("cara.startup", env=settings.env, version=__version__)
    await init_engine()
    cda_attach_redis_url(settings.redis_url)
    try:
        await init_llm_service()
    except LLMUnavailableError as exc:
        # Don't crash the whole API if the LLM fails to load — chat endpoints
        # will return 503, the rest of the app stays usable.
        logger.error("cara.llm_init_failed", error=str(exc))
    if settings.tts_enabled:
        try:
            await init_tts_service(
                voices_dir=settings.tts_voices_dir,
                default_voice=settings.tts_default_voice,
                redis_url=settings.redis_url,
                cache_ttl=settings.tts_cache_ttl_seconds,
                cache_max_chars=settings.tts_cache_max_chars,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("cara.tts_init_failed", error=str(exc))
    try:
        await start_telegram_bot()
    except Exception as exc:  # noqa: BLE001
        logger.error("cara.telegram_start_failed", error=str(exc))
    sm = get_state_machine()
    sm.start_watchdog()
    logger.info("cara.fsm_started", state=sm.state.value)
    start_maintenance()

    # Background reminder scheduler — only started when VAPID is set,
    # otherwise we'd waste a thread polling tasks no one can be pushed to.
    push_task: asyncio.Task | None = None
    if push_is_configured():
        push_task = asyncio.create_task(
            push_scheduler_loop(get_sessionmaker()),
            name="push_scheduler",
        )
        logger.info("cara.push_scheduler_started")
    else:
        logger.info("cara.push_scheduler_skipped", reason="vapid_not_configured")

    # Proactivity engine tick — registers the baseline rules on first
    # tick. Skipped when push isn't configured (no delivery channel).
    proactivity_task: asyncio.Task | None = None
    if push_is_configured():
        proactivity_task = asyncio.create_task(
            proactivity_scheduler_loop(get_sessionmaker()),
            name="proactivity_scheduler",
        )
        logger.info("cara.proactivity_scheduler_started")

    # HA WebSocket events subscriber — runs forever, reconnects on
    # drop, writes state_changed to episodic. Always started; if HA
    # isn't configured the inner loop sleeps and retries.
    ha_events_task: asyncio.Task = asyncio.create_task(
        ha_events_loop(get_sessionmaker()),
        name="ha_events",
    )
    logger.info("cara.ha_events_started")

    # Google Calendar pull scheduler — only when integrations are
    # configured (client_id/secret + encryption key in .env).
    calendar_task: asyncio.Task | None = None
    gmail_task: asyncio.Task | None = None
    if _google_oauth.is_available():
        calendar_task = asyncio.create_task(
            calendar_sync_loop(get_sessionmaker()),
            name="calendar_sync",
        )
        gmail_task = asyncio.create_task(
            gmail_scanner_loop(get_sessionmaker()),
            name="gmail_scanner",
        )
        logger.info("cara.integrations_started")
    else:
        logger.info("cara.integrations_skipped", reason="oauth_not_configured")

    try:
        yield
    finally:
        for t in (push_task, proactivity_task, ha_events_task, calendar_task, gmail_task):
            if t is None:
                continue
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await stop_maintenance()
        await sm.stop_watchdog()
        await stop_telegram_bot()
        await shutdown_tts_service()
        await shutdown_llm_service()
        await shutdown_engine()
        logger.info("cara.shutdown")


app = FastAPI(
    title="CARA",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.env != "production" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.env != "production" else None,
)

app.include_router(api_v1_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — does not exercise external dependencies."""
    return {"status": "ok", "env": settings.env, "version": __version__}


@app.get("/api/v1/ping")
async def ping() -> dict[str, str]:
    return {"pong": "cara"}
