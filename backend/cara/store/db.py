"""Async SQLAlchemy engine, session factory and Base.

The engine is created lazily on first use (via `init_engine` from the FastAPI
lifespan) so that `cara.config` import does not require a live DB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from cara.config import settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    """Common declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def init_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        return
    _engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("db.engine.ready", url=_redacted_url(settings.database_url))


async def shutdown_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
        logger.info("db.engine.closed")


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a session, rollback on error, close after."""
    if _sessionmaker is None:
        raise RuntimeError("DB engine not initialised — call init_engine() first")
    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _redacted_url(url: str) -> str:
    """Hide password from logs (postgresql+asyncpg://user:pwd@host/db)."""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.split("@", 1)
    user = creds.split(":", 1)[0] if ":" in creds else creds
    return f"{scheme}://{user}:***@{host}"
