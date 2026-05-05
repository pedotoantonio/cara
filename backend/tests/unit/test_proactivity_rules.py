"""Unit tests for the 10 concrete proactive rules.

Each rule is exercised in isolation against a constructed RuleContext:
controlled `now` (timezone-aware), a real in-memory db_session (so the
SQL-querying rules work end-to-end), and stub adapters where needed
(weather, smarthome, family).

Coverage shape:
- Time-window rules (morning_greeting, undone_tasks_evening, bedtime_routine,
  shopping_review_saturday, task_overdue_24h): in-window vs out-of-window.
- DB-bound rules: assert correct counts vs. correct text vs. None when
  empty.
- Adapter-bound rules (rain_alert, lights_on_nobody_home): assert
  graceful no-op when adapter missing or returns nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from cara.services.proactivity.engine import RuleContext
from cara.services.proactivity.rules import (
    bedtime_routine,
    birthday_today,
    budget_drift_warning,
    door_open_long,
    lights_on_nobody_home,
    morning_greeting,
    rain_alert,
    registered_rule_ids,
    shopping_review_saturday,
    task_overdue_24h,
    undone_tasks_evening,
)

ROME = ZoneInfo("Europe/Rome")


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ROME)


async def _seed_user(db_session, *, email: str = "ant@example.com"):
    """Create + commit a user, return the persisted instance."""
    from cara.models.user import User

    u = User(
        email=email, full_name="Antonio Pedoto",
        password_hash="x", is_admin=False, is_active=True, role="parent",
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


# ---------------------------------------------------------------------------
# Catalog smoke
# ---------------------------------------------------------------------------


def test_registered_rule_ids_count_is_ten() -> None:
    ids = registered_rule_ids()
    assert len(ids) == 10
    assert len(set(ids)) == 10  # no duplicates


# ---------------------------------------------------------------------------
# 1) morning_greeting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_morning_greeting_skips_outside_window(db_session) -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 11, 0), db_session=db_session)
    assert await morning_greeting(ctx) is None


@pytest.mark.asyncio
async def test_morning_greeting_inside_window_without_db(db_session) -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 8, 0), db_session=None)
    s = await morning_greeting(ctx)
    assert s is not None
    assert "Buongiorno" in s.text


@pytest.mark.asyncio
async def test_morning_greeting_zero_tasks_says_libera(db_session) -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 8, 0), db_session=db_session)
    s = await morning_greeting(ctx)
    assert s is not None
    assert "libera" in s.text.lower()


@pytest.mark.asyncio
async def test_morning_greeting_singular_today(db_session) -> None:
    from cara.models.task import Task
    user = await _seed_user(db_session)
    db_session.add(Task(
        user_id=user.id, title="comprare il pane", done=False,
        due_date=_at(2026, 5, 5, 18, 0),
    ))
    await db_session.commit()
    ctx = RuleContext(now=_at(2026, 5, 5, 8, 0), db_session=db_session)
    s = await morning_greeting(ctx)
    assert s is not None
    assert "1 cosa" in s.text


# ---------------------------------------------------------------------------
# 2) undone_tasks_evening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_undone_evening_silent_outside_window(db_session) -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 14, 0), db_session=db_session)
    assert await undone_tasks_evening(ctx) is None


@pytest.mark.asyncio
async def test_undone_evening_silent_when_no_open(db_session) -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 20, 0), db_session=db_session)
    assert await undone_tasks_evening(ctx) is None


@pytest.mark.asyncio
async def test_undone_evening_quotes_single_task(db_session) -> None:
    from cara.models.task import Task
    user = await _seed_user(db_session)
    db_session.add(Task(
        user_id=user.id, title="pagare bolletta", done=False,
        due_date=_at(2026, 5, 5, 12, 0),
    ))
    await db_session.commit()
    ctx = RuleContext(now=_at(2026, 5, 5, 20, 0), db_session=db_session)
    s = await undone_tasks_evening(ctx)
    assert s is not None
    assert "pagare bolletta" in s.text


# ---------------------------------------------------------------------------
# 3) rain_alert
# ---------------------------------------------------------------------------


class _FakeWeather:
    def __init__(self, forecast: list[dict[str, Any]] | None) -> None:
        self.forecast = forecast

    async def forecast_next_hours(self, hours: int = 3) -> list[dict[str, Any]] | None:
        return self.forecast


@pytest.mark.asyncio
async def test_rain_alert_no_weather_adapter() -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 9, 0), weather=None)
    assert await rain_alert(ctx) is None


@pytest.mark.asyncio
async def test_rain_alert_dry_forecast_silent() -> None:
    ctx = RuleContext(
        now=_at(2026, 5, 5, 9, 0),
        weather=_FakeWeather([{"condition": "sun", "precipitation_mm": 0.0}]),
    )
    assert await rain_alert(ctx) is None


@pytest.mark.asyncio
async def test_rain_alert_fires_on_rain_keyword() -> None:
    ctx = RuleContext(
        now=_at(2026, 5, 5, 9, 0),
        weather=_FakeWeather([{"condition": "Light rain expected", "precipitation_mm": 0.0}]),
    )
    s = await rain_alert(ctx)
    assert s is not None
    assert "ombrello" in s.text.lower()


@pytest.mark.asyncio
async def test_rain_alert_fires_on_precip_threshold() -> None:
    ctx = RuleContext(
        now=_at(2026, 5, 5, 9, 0),
        weather=_FakeWeather([{"condition": "cloud", "precipitation_mm": 1.5}]),
    )
    s = await rain_alert(ctx)
    assert s is not None


@pytest.mark.asyncio
async def test_rain_alert_handles_adapter_exception() -> None:
    class Boom:
        async def forecast_next_hours(self, hours: int = 3) -> list:  # noqa: ARG002
            raise RuntimeError("oops")
    ctx = RuleContext(now=_at(2026, 5, 5, 9, 0), weather=Boom())
    # Should swallow + return None rather than propagating.
    assert await rain_alert(ctx) is None


# ---------------------------------------------------------------------------
# 4) door_open_long (skip — requires Event model + complex setup)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_door_open_long_no_session_returns_none() -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 12, 0), db_session=None)
    assert await door_open_long(ctx) is None


# ---------------------------------------------------------------------------
# 5) bedtime_routine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bedtime_outside_window() -> None:
    assert await bedtime_routine(RuleContext(now=_at(2026, 5, 5, 21, 0))) is None
    assert await bedtime_routine(RuleContext(now=_at(2026, 5, 6, 0, 0))) is None


@pytest.mark.asyncio
async def test_bedtime_inside_window() -> None:
    s = await bedtime_routine(RuleContext(now=_at(2026, 5, 5, 22, 45)))
    assert s is not None
    assert "notte" in s.text.lower()


# ---------------------------------------------------------------------------
# 6) birthday_today
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_birthday_no_session_empty() -> None:
    out = await birthday_today(RuleContext(now=_at(2026, 5, 5, 9, 0), db_session=None))
    assert out == []


@pytest.mark.asyncio
async def test_birthday_too_early_empty(db_session) -> None:
    out = await birthday_today(RuleContext(now=_at(2026, 5, 5, 4, 0), db_session=db_session))
    assert out == []


@pytest.mark.asyncio
async def test_birthday_matches_today(db_session) -> None:
    from datetime import date

    from cara.models.user import User

    db_session.add(User(
        email="sara@example.com", full_name="Sara Rossi",
        password_hash="x", is_admin=False, is_active=True,
        role="parent", birth_date=date(1985, 5, 5),
    ))
    db_session.add(User(
        email="ignored@example.com", full_name="Marco",
        password_hash="x", is_admin=False, is_active=True,
        role="teen", birth_date=date(1990, 11, 12),
    ))
    await db_session.commit()
    out = await birthday_today(RuleContext(now=_at(2026, 5, 5, 9, 0), db_session=db_session))
    assert len(out) == 1
    assert "Sara" in out[0].text
    assert "Buon compleanno" in out[0].text


# ---------------------------------------------------------------------------
# 7) shopping_review_saturday
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shopping_saturday_only_on_saturday(db_session) -> None:
    # 2026-05-05 is a Tuesday.
    ctx = RuleContext(now=_at(2026, 5, 5, 10, 0), db_session=db_session)
    assert await shopping_review_saturday(ctx) is None


@pytest.mark.asyncio
async def test_shopping_saturday_silent_when_empty(db_session) -> None:
    # 2026-05-09 is a Saturday.
    ctx = RuleContext(now=_at(2026, 5, 9, 10, 0), db_session=db_session)
    assert await shopping_review_saturday(ctx) is None


@pytest.mark.asyncio
async def test_shopping_saturday_fires_with_items(db_session) -> None:
    from cara.models.shopping import ShoppingItem
    user = await _seed_user(db_session)
    db_session.add(ShoppingItem(user_id=user.id, title="latte", bought=False))
    db_session.add(ShoppingItem(user_id=user.id, title="pane", bought=False))
    db_session.add(ShoppingItem(user_id=user.id, title="caffe", bought=True))
    await db_session.commit()
    ctx = RuleContext(now=_at(2026, 5, 9, 10, 0), db_session=db_session)
    s = await shopping_review_saturday(ctx)
    assert s is not None
    assert "2 articoli" in s.text


# ---------------------------------------------------------------------------
# 8) task_overdue_24h
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overdue_24h_silent_at_night(db_session) -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 3, 0), db_session=db_session)
    assert await task_overdue_24h(ctx) is None


@pytest.mark.asyncio
async def test_overdue_24h_silent_when_no_overdue(db_session) -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 12, 0), db_session=db_session)
    assert await task_overdue_24h(ctx) is None


@pytest.mark.asyncio
async def test_overdue_24h_singular_message(db_session) -> None:
    from cara.models.task import Task
    user = await _seed_user(db_session)
    db_session.add(Task(
        user_id=user.id, title="rinnovare bollo auto", done=False,
        due_date=_at(2026, 5, 3, 12, 0),  # 2 days ago
    ))
    await db_session.commit()
    ctx = RuleContext(now=_at(2026, 5, 5, 12, 0), db_session=db_session)
    s = await task_overdue_24h(ctx)
    assert s is not None
    assert "rinnovare bollo auto" in s.text


# ---------------------------------------------------------------------------
# 9) budget_drift_warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_drift_no_session() -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 12, 0), db_session=None)
    assert await budget_drift_warning(ctx) is None


# ---------------------------------------------------------------------------
# 10) lights_on_nobody_home
# ---------------------------------------------------------------------------


class _FakeFamily:
    def __init__(self, present: Any) -> None:
        self.present = present

    async def who_is_home(self) -> Any:
        return self.present


class _FakeSmarthome:
    def __init__(self, entities: list[Any] | None) -> None:
        self.entities = entities

    async def list_entities(self) -> list[Any] | None:
        return self.entities


class _Entity:
    def __init__(self, eid: str, domain: str, state: str, name: str | None = None) -> None:
        self.id = eid
        self.domain = domain
        self.state = state
        self.friendly_name = name


@pytest.mark.asyncio
async def test_lights_on_no_adapters() -> None:
    ctx = RuleContext(now=_at(2026, 5, 5, 12, 0))
    assert await lights_on_nobody_home(ctx) is None


@pytest.mark.asyncio
async def test_lights_on_silent_at_night() -> None:
    ctx = RuleContext(
        now=_at(2026, 5, 5, 23, 0),
        smarthome=_FakeSmarthome([_Entity("light.salotto", "light", "on")]),
        family=_FakeFamily([]),
    )
    assert await lights_on_nobody_home(ctx) is None


@pytest.mark.asyncio
async def test_lights_on_silent_when_someone_home() -> None:
    ctx = RuleContext(
        now=_at(2026, 5, 5, 12, 0),
        smarthome=_FakeSmarthome([_Entity("light.salotto", "light", "on")]),
        family=_FakeFamily(["antonio"]),
    )
    assert await lights_on_nobody_home(ctx) is None


@pytest.mark.asyncio
async def test_lights_on_silent_when_no_lights_on() -> None:
    ctx = RuleContext(
        now=_at(2026, 5, 5, 12, 0),
        smarthome=_FakeSmarthome([_Entity("light.salotto", "light", "off")]),
        family=_FakeFamily([]),
    )
    assert await lights_on_nobody_home(ctx) is None


@pytest.mark.asyncio
async def test_lights_on_fires_singular() -> None:
    ctx = RuleContext(
        now=_at(2026, 5, 5, 12, 0),
        smarthome=_FakeSmarthome([
            _Entity("light.salotto", "light", "on", "Salotto"),
        ]),
        family=_FakeFamily([]),
    )
    s = await lights_on_nobody_home(ctx)
    assert s is not None
    assert "Salotto" in s.text


@pytest.mark.asyncio
async def test_lights_on_fires_plural() -> None:
    ctx = RuleContext(
        now=_at(2026, 5, 5, 12, 0),
        smarthome=_FakeSmarthome([
            _Entity("light.salotto", "light", "on"),
            _Entity("light.cucina", "light", "on"),
            _Entity("light.bagno", "light", "off"),
        ]),
        family=_FakeFamily({"count": 0}),
    )
    s = await lights_on_nobody_home(ctx)
    assert s is not None
    assert "2 luci" in s.text
