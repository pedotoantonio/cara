"""Unit tests for `cara.services.proactivity.engine`."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from cara.services.proactivity import (
    Priority,
    ProactivityEngine,
    RuleContext,
    Suggestion,
    register_rule,
    registry,
)
from cara.services.proactivity.engine import EngineConfig, _RuleRegistry


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- helpers


def _ctx(hour: int = 14, minute: int = 0) -> RuleContext:
    """Build a RuleContext at a chosen wall-clock time, UTC for tests
    (we don't need real Europe/Rome conversion here)."""
    return RuleContext(
        now=datetime(2026, 5, 4, hour, minute, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------- rule registration


async def test_register_and_evaluate_returns_suggestion() -> None:
    reg = _RuleRegistry()

    async def fire(ctx):  # noqa: ARG001
        return Suggestion(rule_id="x", text="hello", priority=Priority.MEDIUM)

    reg.register("x", fire)
    engine = ProactivityEngine(reg)
    out = await engine.evaluate(_ctx())
    assert len(out) == 1
    assert out[0].text == "hello"


async def test_register_via_decorator() -> None:
    """@rule decorator hits the global registry. Save state and restore."""
    saved = registry.all()
    registry.reset_for_test()

    from cara.services.proactivity import rule

    @rule("decorated", cooldown_hours=1.0)
    async def decorated(ctx):  # noqa: ARG001
        return Suggestion(rule_id="decorated", text="dec")

    try:
        engine = ProactivityEngine(registry)
        out = await engine.evaluate(_ctx())
        assert any(s.rule_id == "decorated" for s in out)
    finally:
        registry.reset_for_test()
        for s in saved:
            registry.register(
                s.rule_id, s.callable,
                cooldown_hours=s.cooldown_hours,
                enabled=s.enabled, description=s.description,
            )


# ---------------------------------------------------------------- rule isolation


async def test_rule_exception_does_not_break_engine() -> None:
    reg = _RuleRegistry()

    async def boom(ctx):  # noqa: ARG001
        raise RuntimeError("oops")

    async def fine(ctx):  # noqa: ARG001
        return Suggestion(rule_id="fine", text="ok")

    reg.register("boom", boom)
    reg.register("fine", fine)
    engine = ProactivityEngine(reg)
    out = await engine.evaluate(_ctx())
    assert [s.rule_id for s in out] == ["fine"]


async def test_rule_returning_none_emits_nothing() -> None:
    reg = _RuleRegistry()

    async def silent(ctx):  # noqa: ARG001
        return None

    reg.register("silent", silent)
    engine = ProactivityEngine(reg)
    out = await engine.evaluate(_ctx())
    assert out == []


async def test_rule_returning_iterable_yields_multiple() -> None:
    reg = _RuleRegistry()

    async def many(ctx):  # noqa: ARG001
        return [
            Suggestion(rule_id="many", text="a"),
            Suggestion(rule_id="many", text="b"),
        ]

    reg.register("many", many)
    engine = ProactivityEngine(reg)
    out = await engine.evaluate(_ctx())
    assert [s.text for s in out] == ["a", "b"]


# ---------------------------------------------------------------- cooldown


async def test_cooldown_blocks_second_fire() -> None:
    reg = _RuleRegistry()

    async def fire(ctx):  # noqa: ARG001
        return Suggestion(rule_id="x", text="hit")

    reg.register("x", fire, cooldown_hours=24.0)
    engine = ProactivityEngine(reg)

    out1 = await engine.evaluate(_ctx())
    assert len(out1) == 1
    out2 = await engine.evaluate(_ctx(hour=15))  # 1h later — still in cooldown
    assert out2 == []


async def test_cooldown_expires_after_window() -> None:
    reg = _RuleRegistry()

    async def fire(ctx):  # noqa: ARG001
        return Suggestion(rule_id="x", text="hit")

    reg.register("x", fire, cooldown_hours=1.0)
    engine = ProactivityEngine(reg)

    base = datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc)
    await engine.evaluate(RuleContext(now=base))
    # Two hours later → cooldown elapsed.
    out = await engine.evaluate(RuleContext(now=base + timedelta(hours=2)))
    assert len(out) == 1


# ---------------------------------------------------------------- enabled flag


async def test_disabled_rule_never_fires() -> None:
    reg = _RuleRegistry()

    async def fire(ctx):  # noqa: ARG001
        return Suggestion(rule_id="x", text="hit")

    reg.register("x", fire)
    reg.set_enabled("x", False)

    engine = ProactivityEngine(reg)
    out = await engine.evaluate(_ctx())
    assert out == []


async def test_engine_disabled_short_circuits() -> None:
    reg = _RuleRegistry()

    async def fire(ctx):  # noqa: ARG001
        return Suggestion(rule_id="x", text="hit")

    reg.register("x", fire)
    engine = ProactivityEngine(reg)
    cfg = EngineConfig(enabled=False)
    out = await engine.evaluate(_ctx(), config=cfg)
    assert out == []


# ---------------------------------------------------------------- silent hours


async def test_silent_hours_drop_low_priority() -> None:
    reg = _RuleRegistry()

    async def low(ctx):  # noqa: ARG001
        return Suggestion(rule_id="low", text="x", priority=Priority.LOW)

    async def urgent(ctx):  # noqa: ARG001
        return Suggestion(rule_id="urgent", text="x", priority=Priority.URGENT)

    reg.register("low", low)
    reg.register("urgent", urgent)
    engine = ProactivityEngine(reg)

    cfg = EngineConfig(
        silent_start=time(22, 0),
        silent_end=time(7, 0),
        silent_min_priority=Priority.URGENT,
    )
    # 23:30 — inside silent window
    out = await engine.evaluate(_ctx(hour=23, minute=30), config=cfg)
    assert [s.rule_id for s in out] == ["urgent"]


async def test_silent_hours_pass_through_during_day() -> None:
    reg = _RuleRegistry()

    async def low(ctx):  # noqa: ARG001
        return Suggestion(rule_id="low", text="x", priority=Priority.LOW)

    reg.register("low", low)
    engine = ProactivityEngine(reg)

    cfg = EngineConfig(silent_start=time(22, 0), silent_end=time(7, 0))
    out = await engine.evaluate(_ctx(hour=15), config=cfg)
    assert len(out) == 1


async def test_silent_hours_handle_overnight_wrap() -> None:
    """22:00..07:00 wraps over midnight. 02:00 must be silent."""
    reg = _RuleRegistry()

    async def low(ctx):  # noqa: ARG001
        return Suggestion(rule_id="low", text="x", priority=Priority.LOW)

    reg.register("low", low)
    engine = ProactivityEngine(reg)

    cfg = EngineConfig(silent_start=time(22, 0), silent_end=time(7, 0))
    out = await engine.evaluate(_ctx(hour=2), config=cfg)
    assert out == []


async def test_silent_hours_equal_window_disables() -> None:
    """`start == end` is a no-op (no silent hours)."""
    reg = _RuleRegistry()

    async def low(ctx):  # noqa: ARG001
        return Suggestion(rule_id="low", text="x", priority=Priority.LOW)

    reg.register("low", low)
    engine = ProactivityEngine(reg)

    cfg = EngineConfig(silent_start=time(0, 0), silent_end=time(0, 0))
    out = await engine.evaluate(_ctx(hour=2), config=cfg)
    assert len(out) == 1


# ---------------------------------------------------------------- registry helpers


def test_registry_set_enabled_unknown_rule_returns_false() -> None:
    reg = _RuleRegistry()
    assert reg.set_enabled("missing", False) is False


def test_registry_unregister_drops_rule() -> None:
    reg = _RuleRegistry()

    async def fire(ctx):  # noqa: ARG001
        return None

    reg.register("x", fire)
    assert reg.get("x") is not None
    reg.unregister("x")
    assert reg.get("x") is None


# ---------------------------------------------------------------- Suggestion + Priority


def test_suggestion_is_urgent_property() -> None:
    s = Suggestion(rule_id="x", text="x", priority=Priority.URGENT)
    assert s.is_urgent is True
    s2 = Suggestion(rule_id="x", text="x", priority=Priority.LOW)
    assert s2.is_urgent is False


def test_priority_int_ordering() -> None:
    assert Priority.LOW < Priority.MEDIUM < Priority.HIGH < Priority.URGENT
