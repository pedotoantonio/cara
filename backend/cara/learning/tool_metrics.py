"""Tool-call telemetry recording + aggregations for the admin dashboard.

Two responsibilities:

1. Record (`record_attempt`): one call per tool-call attempt anywhere in
   the system. Designed to be cheap and never raise — telemetry must NEVER
   break the hot path.
2. Aggregate (`stats`, `recent_failures`, `top_failure_classes`): SQL
   summaries the admin diagnostics page consumes.

Truncates `raw_call` to 500 chars so a runaway model output can't blow up
the table.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.tool_metric import ToolCallMetric
from cara.store.db import get_sessionmaker


log = structlog.get_logger(__name__)


_RAW_CALL_MAX = 500


# Canonical error_class slugs — keep this list short and stable so SQL
# aggregations stay meaningful across releases.
ERROR_PARSE_TYPO_PREFIX = "typo_prefix"
ERROR_PARSE_MALFORMED = "parse_malformed"
ERROR_UNKNOWN_TOOL = "unknown_tool"
ERROR_MISSING_ARG = "missing_arg"
ERROR_SCHEMA_INVALID = "schema_invalid"
ERROR_PERMISSION_DENIED = "permission_denied"
ERROR_EXEC_EXCEPTION = "exec_exception"


async def record_attempt(
    session: AsyncSession,
    *,
    parse_ok: bool,
    name_match: bool = False,
    args_valid: bool = False,
    executed: bool = False,
    tool_name: str | None = None,
    error_class: str | None = None,
    raw_call: str | None = None,
    user_id: int | None = None,
    conversation_id: str | None = None,
    duration_ms: int | float | None = None,
    commit: bool = False,
) -> ToolCallMetric:
    """Persist one tool-call attempt row."""
    metric = ToolCallMetric(
        parse_ok=parse_ok,
        name_match=name_match,
        args_valid=args_valid,
        executed=executed,
        tool_name=tool_name,
        error_class=error_class,
        raw_call=(raw_call or "")[:_RAW_CALL_MAX] if raw_call else None,
        user_id=user_id,
        conversation_id=conversation_id,
        duration_ms=int(duration_ms) if duration_ms is not None else None,
    )
    session.add(metric)
    await session.flush()
    if commit:
        await session.commit()
    return metric


async def record_attempt_async(
    *,
    parse_ok: bool,
    name_match: bool = False,
    args_valid: bool = False,
    executed: bool = False,
    tool_name: str | None = None,
    error_class: str | None = None,
    raw_call: str | None = None,
    user_id: int | None = None,
    conversation_id: str | None = None,
    duration_ms: int | float | None = None,
) -> None:
    """Fire-and-forget recording. Errors are logged, not raised."""
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            await record_attempt(
                session,
                parse_ok=parse_ok,
                name_match=name_match,
                args_valid=args_valid,
                executed=executed,
                tool_name=tool_name,
                error_class=error_class,
                raw_call=raw_call,
                user_id=user_id,
                conversation_id=conversation_id,
                duration_ms=duration_ms,
                commit=True,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("tool_metrics.record_async.failed", error=str(exc))


@dataclass
class ToolStats:
    total: int
    parse_ok: int
    name_match: int
    args_valid: int
    executed: int

    @property
    def parse_rate(self) -> float:
        return self.parse_ok / self.total if self.total else 0.0

    @property
    def success_rate(self) -> float:
        """Share of attempts that fully executed. The headline number."""
        return self.executed / self.total if self.total else 0.0


async def stats(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    tool_name: str | None = None,
) -> ToolStats:
    """High-level success funnel: how many attempts cleared each gate?"""
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=7)

    base = select(ToolCallMetric).where(ToolCallMetric.ts >= since)
    if tool_name is not None:
        base = base.where(ToolCallMetric.tool_name == tool_name)

    total_q = select(func.count()).select_from(base.subquery())
    total = (await session.execute(total_q)).scalar_one()

    if total == 0:
        return ToolStats(0, 0, 0, 0, 0)

    parse_q = select(func.count()).select_from(
        base.where(ToolCallMetric.parse_ok.is_(True)).subquery()
    )
    name_q = select(func.count()).select_from(
        base.where(ToolCallMetric.name_match.is_(True)).subquery()
    )
    args_q = select(func.count()).select_from(
        base.where(ToolCallMetric.args_valid.is_(True)).subquery()
    )
    exec_q = select(func.count()).select_from(
        base.where(ToolCallMetric.executed.is_(True)).subquery()
    )

    return ToolStats(
        total=total,
        parse_ok=(await session.execute(parse_q)).scalar_one(),
        name_match=(await session.execute(name_q)).scalar_one(),
        args_valid=(await session.execute(args_q)).scalar_one(),
        executed=(await session.execute(exec_q)).scalar_one(),
    )


async def top_failure_classes(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    limit: int = 10,
) -> list[tuple[str, int]]:
    """Most frequent error_class values in the window. (class, count)."""
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=7)
    stmt = (
        select(ToolCallMetric.error_class, func.count().label("n"))
        .where(ToolCallMetric.ts >= since)
        .where(ToolCallMetric.error_class.is_not(None))
        .group_by(ToolCallMetric.error_class)
        .order_by(desc("n"))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def recent_failures(
    session: AsyncSession,
    *,
    limit: int = 20,
    error_classes: Iterable[str] | None = None,
) -> list[ToolCallMetric]:
    """Newest-first list of failed attempts (executed=False) for triage."""
    stmt = (
        select(ToolCallMetric)
        .where(ToolCallMetric.executed.is_(False))
        .order_by(ToolCallMetric.ts.desc())
        .limit(limit)
    )
    if error_classes is not None:
        ec = list(error_classes)
        if ec:
            stmt = stmt.where(ToolCallMetric.error_class.in_(ec))
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)
