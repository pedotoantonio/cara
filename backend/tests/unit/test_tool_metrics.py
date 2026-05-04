"""Unit tests for `cara.learning.tool_metrics`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cara.learning import tool_metrics
from cara.learning.tool_metrics import (
    ERROR_MISSING_ARG,
    ERROR_PARSE_TYPO_PREFIX,
    ERROR_UNKNOWN_TOOL,
)


pytestmark = pytest.mark.asyncio


async def test_record_full_success_attempt(db_session) -> None:
    m = await tool_metrics.record_attempt(
        db_session,
        parse_ok=True,
        name_match=True,
        args_valid=True,
        executed=True,
        tool_name="add_task",
        duration_ms=15,
    )
    assert m.id is not None
    assert m.executed is True
    assert m.error_class is None


async def test_record_parse_failure(db_session) -> None:
    m = await tool_metrics.record_attempt(
        db_session,
        parse_ok=False,
        error_class=ERROR_PARSE_TYPO_PREFIX,
        raw_call="TUTOOL: add_task(...)",
    )
    assert m.parse_ok is False
    assert m.name_match is False
    assert m.error_class == ERROR_PARSE_TYPO_PREFIX
    assert m.raw_call == "TUTOOL: add_task(...)"


async def test_raw_call_is_truncated_at_500_chars(db_session) -> None:
    huge = "x" * 5000
    m = await tool_metrics.record_attempt(
        db_session, parse_ok=False, raw_call=huge, error_class=ERROR_PARSE_TYPO_PREFIX
    )
    assert m.raw_call is not None
    assert len(m.raw_call) == 500


async def test_stats_returns_zeros_when_empty(db_session) -> None:
    s = await tool_metrics.stats(db_session)
    assert s.total == 0
    assert s.success_rate == 0.0
    assert s.parse_rate == 0.0


async def test_stats_funnel_counts_each_gate(db_session) -> None:
    await tool_metrics.record_attempt(
        db_session, parse_ok=True, name_match=True, args_valid=True, executed=True,
        tool_name="add_task",
    )
    await tool_metrics.record_attempt(
        db_session, parse_ok=True, name_match=True, args_valid=True, executed=True,
        tool_name="add_task",
    )
    await tool_metrics.record_attempt(
        db_session, parse_ok=True, name_match=True, args_valid=False,
        tool_name="add_task", error_class=ERROR_MISSING_ARG,
    )
    await tool_metrics.record_attempt(
        db_session, parse_ok=False, error_class=ERROR_PARSE_TYPO_PREFIX,
    )
    await db_session.commit()

    s = await tool_metrics.stats(db_session)
    assert s.total == 4
    assert s.parse_ok == 3
    assert s.name_match == 3
    assert s.args_valid == 2
    assert s.executed == 2
    assert s.success_rate == 0.5
    assert s.parse_rate == 0.75


async def test_stats_filters_by_tool_name(db_session) -> None:
    await tool_metrics.record_attempt(
        db_session, parse_ok=True, name_match=True, args_valid=True, executed=True,
        tool_name="add_task",
    )
    await tool_metrics.record_attempt(
        db_session, parse_ok=False, tool_name="play_radio",
        error_class=ERROR_PARSE_TYPO_PREFIX,
    )
    await db_session.commit()

    s = await tool_metrics.stats(db_session, tool_name="add_task")
    assert s.total == 1
    assert s.executed == 1


async def test_stats_filters_by_since(db_session) -> None:
    old = await tool_metrics.record_attempt(db_session, parse_ok=True)
    old.ts = datetime.now(timezone.utc) - timedelta(days=30)
    await tool_metrics.record_attempt(db_session, parse_ok=True)
    await db_session.commit()

    s = await tool_metrics.stats(
        db_session, since=datetime.now(timezone.utc) - timedelta(days=1)
    )
    assert s.total == 1


async def test_top_failure_classes_orders_by_count(db_session) -> None:
    for _ in range(3):
        await tool_metrics.record_attempt(
            db_session, parse_ok=False, error_class=ERROR_PARSE_TYPO_PREFIX,
        )
    for _ in range(5):
        await tool_metrics.record_attempt(
            db_session, parse_ok=True, name_match=False, error_class=ERROR_UNKNOWN_TOOL,
        )
    await tool_metrics.record_attempt(
        db_session, parse_ok=True, name_match=True, args_valid=False,
        error_class=ERROR_MISSING_ARG,
    )
    await db_session.commit()

    top = await tool_metrics.top_failure_classes(db_session)
    assert top[0] == (ERROR_UNKNOWN_TOOL, 5)
    assert top[1] == (ERROR_PARSE_TYPO_PREFIX, 3)
    assert top[2] == (ERROR_MISSING_ARG, 1)


async def test_recent_failures_excludes_executed(db_session) -> None:
    await tool_metrics.record_attempt(
        db_session, parse_ok=True, name_match=True, args_valid=True, executed=True,
        tool_name="add_task",
    )
    await tool_metrics.record_attempt(
        db_session, parse_ok=False, error_class=ERROR_PARSE_TYPO_PREFIX,
    )
    await db_session.commit()

    failures = await tool_metrics.recent_failures(db_session, limit=10)
    assert len(failures) == 1
    assert failures[0].executed is False


async def test_recent_failures_filters_by_class(db_session) -> None:
    await tool_metrics.record_attempt(
        db_session, parse_ok=False, error_class=ERROR_PARSE_TYPO_PREFIX,
    )
    await tool_metrics.record_attempt(
        db_session, parse_ok=True, name_match=False, error_class=ERROR_UNKNOWN_TOOL,
    )
    await db_session.commit()

    only_parse = await tool_metrics.recent_failures(
        db_session, error_classes=[ERROR_PARSE_TYPO_PREFIX]
    )
    assert len(only_parse) == 1
    assert only_parse[0].error_class == ERROR_PARSE_TYPO_PREFIX
