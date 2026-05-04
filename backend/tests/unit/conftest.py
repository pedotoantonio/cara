"""Unit-test fixtures: in-memory SQLite session for ORM tests.

The smoke tests (in `tests/smoke/`) hit the real backend over HTTP. Unit
tests don't need a running backend or a real Postgres — we spin up a
fresh in-memory SQLite DB per test, run the table DDL we need, and tear
it all down at the end of the test.

This keeps each unit test fast (<50 ms) and independent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import BigInteger, event as sa_event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

# Postgres-only types compiled as their closest SQLite equivalent so the
# in-memory test DB can hold the same schema.
#   JSONB → JSON, UUID → CHAR(36), BigInteger → INTEGER (the latter so
#   SQLite's ROWID auto-increment kicks in for primary keys).
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ARG001
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001, ARG001
    return "CHAR(36)"


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):  # noqa: ANN001, ARG001
    return "INTEGER"


# Importing models is enough to register them on Base.metadata.
import cara.models  # noqa: E402, F401 — side-effect import
# These aren't yet in cara/models/__init__ to avoid a merge conflict
# with Antonio's Step 66 working tree, so import them explicitly.
from cara.models.device import Device  # noqa: E402, F401
from cara.models.device_permission import DevicePermission  # noqa: E402, F401
from cara.models.event import Event  # noqa: E402, F401
from cara.models.fact import Fact  # noqa: E402, F401
from cara.models.habit import HabitCandidate  # noqa: E402, F401
from cara.models.tool_metric import ToolCallMetric  # noqa: E402, F401
from cara.models.user import User  # noqa: E402, F401
from cara.store.db import Base  # noqa: E402


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A fresh in-memory SQLite DB per test.

    Dialect-specific column types (JSONB, UUID) are mapped to JSON / String
    by SQLAlchemy's compatibility layer when the dialect is sqlite, so most
    Postgres-shaped models work in-memory too. For tests that genuinely need
    Postgres (pgvector, JSONB ops, etc.), use the smoke suite instead.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Enable FK constraints in SQLite (off by default).
    @sa_event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_con, _):  # noqa: ANN001
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session

    await engine.dispose()
