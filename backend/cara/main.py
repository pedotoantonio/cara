"""CARA backend entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from cara import __version__
from cara.ai.llm import LLMUnavailableError, init_llm_service, shutdown_llm_service
from cara.ai.tts import init_tts_service, shutdown_tts_service
from cara.api.v1 import router as api_v1_router
from cara.config import settings
from cara.integrations.telegram import start_telegram_bot, stop_telegram_bot
from cara.store import init_engine, shutdown_engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("cara.startup", env=settings.env, version=__version__)
    await init_engine()
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
    try:
        yield
    finally:
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
