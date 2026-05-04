"""Proactivity engine internals."""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import IntEnum
from typing import Any

import structlog


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Priority — controls silent-hours filtering
# ---------------------------------------------------------------------------


class Priority(IntEnum):
    """Higher number = more urgent. Silent hours mute everything except
    URGENT (and admin-configurable threshold, default URGENT)."""

    LOW = 10              # ambient suggestions ("budget drift"); always silent-hours muted
    MEDIUM = 30           # gentle nudges ("nessuno è in casa, spengo le luci?")
    HIGH = 60             # actionable ("porta aperta da 5 minuti, fa freddo")
    URGENT = 90           # bypasses silent hours ("allarme attivato")


# ---------------------------------------------------------------------------
# Suggestion — what a rule produces
# ---------------------------------------------------------------------------


@dataclass
class Suggestion:
    """Single proactive prompt the user sees as a card.

    `target_user_id`: who to surface this to. `None` = whole family.
    `action`: optional structured payload the UI uses to render a
    one-tap action button (e.g. `{"tool": "scene_activate",
    "args": {"scene": "uscita_casa"}}`). The user reviews + confirms.
    """

    rule_id: str
    text: str
    priority: Priority = Priority.MEDIUM
    target_user_id: int | None = None
    action: dict[str, Any] | None = None
    expires_at: datetime | None = None        # auto-purge stale suggestions

    @property
    def is_urgent(self) -> bool:
        return self.priority >= Priority.URGENT


# ---------------------------------------------------------------------------
# RuleContext — what a rule reads from
# ---------------------------------------------------------------------------


@dataclass
class RuleContext:
    """Whatever a rule may need. Passed by the engine on every tick.

    Designed wide so adding a new rule never requires touching the
    engine signature. Rules read only what they need; the rest is
    free zero-cost overhead.

    Required:
      `now`: timezone-aware datetime in Europe/Rome (engine default).

    Optional adapters injected by the host application:
      `smarthome`: SmartHomeAdapter (Step 5.x)
      `weather`:   WeatherService (Step 8.1)
      `family`:    presence service hook
      `db_session`: AsyncSession bound for the tick
      `extras`: free-form scratchpad
    """

    now: datetime
    smarthome: Any | None = None
    weather: Any | None = None
    family: Any | None = None
    db_session: Any | None = None
    extras: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Rule — the callable + its metadata
# ---------------------------------------------------------------------------


# A rule is an async callable that takes a RuleContext and returns
# zero, one, or many Suggestions. None / empty list / any iterable.
RuleCallable = Callable[
    [RuleContext],
    Awaitable[Suggestion | Iterable[Suggestion] | None],
]


@dataclass
class _RuleEntry:
    rule_id: str
    callable: RuleCallable
    cooldown_hours: float
    enabled: bool = True
    description: str = ""
    last_fired_at: datetime | None = None  # for cooldown tracking


# ---------------------------------------------------------------------------
# Registry — process-wide list of registered rules
# ---------------------------------------------------------------------------


class _RuleRegistry:
    """Thread-safe registry. Rules can be registered at import time via
    the `@rule` decorator or at runtime via `register_rule`."""

    def __init__(self) -> None:
        self._rules: dict[str, _RuleEntry] = {}
        self._lock = threading.Lock()

    def register(
        self,
        rule_id: str,
        fn: RuleCallable,
        *,
        cooldown_hours: float = 24.0,
        enabled: bool = True,
        description: str = "",
    ) -> None:
        with self._lock:
            self._rules[rule_id] = _RuleEntry(
                rule_id=rule_id,
                callable=fn,
                cooldown_hours=cooldown_hours,
                enabled=enabled,
                description=description,
            )

    def unregister(self, rule_id: str) -> None:
        with self._lock:
            self._rules.pop(rule_id, None)

    def get(self, rule_id: str) -> _RuleEntry | None:
        with self._lock:
            return self._rules.get(rule_id)

    def all(self) -> list[_RuleEntry]:
        with self._lock:
            return list(self._rules.values())

    def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        with self._lock:
            entry = self._rules.get(rule_id)
            if entry is None:
                return False
            entry.enabled = enabled
            return True

    def reset_for_test(self) -> None:
        with self._lock:
            self._rules.clear()


registry = _RuleRegistry()


def rule(
    rule_id: str,
    *,
    cooldown_hours: float = 24.0,
    enabled: bool = True,
    description: str = "",
):
    """Decorator: register an async function as a proactivity rule.

    Usage:
        @rule("door_open_long", cooldown_hours=2.0)
        async def door_open_long(ctx: RuleContext) -> Suggestion | None:
            ...
    """

    def decorator(fn: RuleCallable) -> RuleCallable:
        registry.register(
            rule_id, fn,
            cooldown_hours=cooldown_hours,
            enabled=enabled, description=description,
        )
        return fn

    return decorator


def register_rule(
    rule_id: str,
    fn: RuleCallable,
    *,
    cooldown_hours: float = 24.0,
    enabled: bool = True,
    description: str = "",
) -> None:
    """Imperative form for tests or runtime registration."""
    registry.register(
        rule_id, fn,
        cooldown_hours=cooldown_hours, enabled=enabled, description=description,
    )


# ---------------------------------------------------------------------------
# Engine — orchestrates a tick
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    """Per-tick configuration. Read once per tick from admin_settings."""

    silent_start: time = time(22, 0)
    silent_end: time = time(7, 0)
    silent_min_priority: Priority = Priority.URGENT
    enabled: bool = True


class ProactivityEngine:
    """Walk every enabled rule, collect surviving Suggestions.

    `evaluate(ctx, config)` is the single entry point. Returns a list
    of Suggestion objects ready to persist into the queue table.

    Design choices:

    - **Rule isolation**: a rule that raises is logged and skipped;
      the others still get to run.
    - **Cooldown**: the engine enforces it itself (using
      `entry.last_fired_at`), so individual rules don't have to. A
      Suggestion that survives cooldown bumps the entry's timestamp.
    - **Silent hours**: priority < `silent_min_priority` is dropped if
      the current time is inside the `[silent_start, silent_end]`
      window (handles overnight wrap-around).
    """

    def __init__(self, registry_inst: _RuleRegistry = registry) -> None:
        self._registry = registry_inst

    async def evaluate(
        self,
        ctx: RuleContext,
        *,
        config: EngineConfig | None = None,
    ) -> list[Suggestion]:
        cfg = config or EngineConfig()
        if not cfg.enabled:
            return []

        in_silent = self._is_silent_hour(ctx.now, cfg.silent_start, cfg.silent_end)
        out: list[Suggestion] = []

        for entry in self._registry.all():
            if not entry.enabled:
                continue
            if not self._cooldown_ok(entry, ctx.now):
                continue

            try:
                result = await entry.callable(ctx)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "proactivity.rule.exception",
                    rule_id=entry.rule_id, error=str(exc),
                )
                continue

            suggestions = self._normalise_result(result, entry.rule_id)
            if not suggestions:
                continue

            kept = []
            for s in suggestions:
                if in_silent and s.priority < cfg.silent_min_priority:
                    continue
                kept.append(s)
            if not kept:
                continue

            entry.last_fired_at = ctx.now
            out.extend(kept)

        return out

    @staticmethod
    def _normalise_result(
        result: Suggestion | Iterable[Suggestion] | None,
        rule_id: str,
    ) -> list[Suggestion]:
        if result is None:
            return []
        if isinstance(result, Suggestion):
            return [result]
        out: list[Suggestion] = []
        for s in result:
            if isinstance(s, Suggestion):
                out.append(s)
            else:
                log.warning(
                    "proactivity.rule.invalid_yield",
                    rule_id=rule_id, type=type(s).__name__,
                )
        return out

    @staticmethod
    def _cooldown_ok(entry: _RuleEntry, now: datetime) -> bool:
        if entry.last_fired_at is None:
            return True
        elapsed = now - entry.last_fired_at
        return elapsed >= timedelta(hours=entry.cooldown_hours)

    @staticmethod
    def _is_silent_hour(
        now: datetime, start: time, end: time,
    ) -> bool:
        """True if `now`'s wall-clock time is inside the silent window.

        Handles overnight wrap (e.g. 22:00..07:00 the next morning).
        Comparison is done on local wall-clock time — `now` should be
        timezone-aware in the family's zone.
        """
        cur = now.time()
        if start == end:
            return False
        if start < end:
            return start <= cur < end
        # Overnight wrap.
        return cur >= start or cur < end


# Module-level convenience: the canonical engine bound to the global registry.
default_engine = ProactivityEngine(registry)


def now_in_zone(tz_name: str = "Europe/Rome") -> datetime:
    """Helper for rules that need a timezone-aware `now`."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(tz_name))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
