"""Unit tests for the 6 extra widgets (Step 7.6)."""

from __future__ import annotations

from typing import Any

import pytest

from cara.widgets.base import WidgetContext, WidgetSize
from cara.widgets.catalog_extra import (
    BudgetMonthWidget,
    CaraQuoteWidget,
    KidsHomeworkWidget,
    NewsBriefWidget,
    RadioNowPlayingWidget,
    RoutineNextWidget,
    _ExtraFetchers,
)


pytestmark = pytest.mark.asyncio


def _ctx(**overrides) -> WidgetContext:
    base = {
        "user_id": 1, "user_role": "parent",
        "surface_class": "mobile", "locale": "it-IT",
        "timezone": "Europe/Rome",
    }
    base.update(overrides)
    return WidgetContext(**base)


# ---------------------------------------------------------------- budget_month


async def test_budget_month_unavailable_when_no_fetcher() -> None:
    w = BudgetMonthWidget(_ExtraFetchers())
    out = await w.render(_ctx())
    assert out.body["available"] is False


async def test_budget_month_renders_rollup() -> None:
    async def fake(year: int, month: int):
        return {
            "year": year, "month": month,
            "total_spent_cents": 12345,
            "total_target_cents": 50000,
            "categories": [{"category": "groceries", "spent_cents": 12345}],
        }
    w = BudgetMonthWidget(_ExtraFetchers(budget_rollup=fake))
    out = await w.render(_ctx())
    assert out.body["available"] is True
    assert out.body["total_spent_cents"] == 12345


async def test_budget_month_swallows_fetcher_failure() -> None:
    async def boom(_y, _m):
        raise RuntimeError("db down")
    w = BudgetMonthWidget(_ExtraFetchers(budget_rollup=boom))
    out = await w.render(_ctx())
    assert out.body["available"] is False
    assert out.body.get("error") == "rollup_failed"


# ---------------------------------------------------------------- kids_homework


async def test_kids_homework_lists_items() -> None:
    async def fake(uid: int):
        return [
            {"id": "1", "title": "Compiti italiano", "done": False, "due_unix": None},
            {"id": "2", "title": "Compiti matematica", "done": False, "due_unix": None},
        ]
    w = KidsHomeworkWidget(_ExtraFetchers(kids_homework=fake))
    out = await w.render(_ctx())
    assert out.body["total"] == 2
    assert len(out.body["items"]) == 2


async def test_kids_homework_caps_by_size() -> None:
    async def fake(uid: int):
        return [{"id": str(i), "title": f"compito {i}", "done": False} for i in range(20)]
    w = KidsHomeworkWidget(_ExtraFetchers(kids_homework=fake))
    out_small = await w.render(_ctx(), size=WidgetSize.SMALL)
    out_large = await w.render(_ctx(), size=WidgetSize.LARGE)
    assert len(out_small.body["items"]) == 2
    assert len(out_large.body["items"]) == 8


async def test_kids_homework_no_user_id_empty() -> None:
    async def fake(uid: int):  # noqa: ARG001
        return [{"id": "x", "title": "y"}]
    w = KidsHomeworkWidget(_ExtraFetchers(kids_homework=fake))
    out = await w.render(_ctx(user_id=None))
    assert out.body["items"] == []


# ---------------------------------------------------------------- routine_next


async def test_routine_next_unavailable_when_empty() -> None:
    async def fake(uid: int):
        return []
    w = RoutineNextWidget(_ExtraFetchers(habit_next=fake))
    out = await w.render(_ctx())
    assert out.body["available"] is False


async def test_routine_next_returns_top_with_human_labels() -> None:
    async def fake(uid: int):
        return [
            {
                "kind": "task.created",
                "weekday": 1,            # martedì
                "hour_bucket": 6,         # 18-21
                "pattern": {"category": "spesa"},
                "last_seen": None,
            },
            {"kind": "shopping.add", "weekday": 3, "hour_bucket": 4, "pattern": {}},
        ]
    w = RoutineNextWidget(_ExtraFetchers(habit_next=fake))
    out = await w.render(_ctx())
    assert out.body["available"] is True
    assert out.body["weekday_label"] == "mar"
    assert out.body["hour_label"] == "18-21"
    assert out.body["pattern"] == {"category": "spesa"}


async def test_routine_next_swallows_fetcher_failure() -> None:
    async def boom(uid: int):
        raise RuntimeError("DB lost")
    w = RoutineNextWidget(_ExtraFetchers(habit_next=boom))
    out = await w.render(_ctx())
    assert out.body["available"] is False


# ---------------------------------------------------------------- cara_quote


async def test_cara_quote_returns_a_quote() -> None:
    w = CaraQuoteWidget()
    out = await w.render(_ctx())
    assert out.body["quote"]
    assert isinstance(out.body["quote"], str)
    assert 0 <= out.body["index"] < out.body["total"]


async def test_cara_quote_deterministic_by_day() -> None:
    """Calling render twice in the same day returns the same quote."""
    w = CaraQuoteWidget()
    out1 = await w.render(_ctx())
    out2 = await w.render(_ctx())
    assert out1.body["quote"] == out2.body["quote"]


# ---------------------------------------------------------------- news_brief


async def test_news_brief_returns_items_under_limit() -> None:
    async def fake(category: str, limit: int):
        return [
            {"title": f"news {i}", "summary": "x", "source": "rai", "link": "l"}
            for i in range(5)
        ]
    w = NewsBriefWidget(_ExtraFetchers(news_brief=fake), limit=3)
    out = await w.render(_ctx())
    assert len(out.body["items"]) == 3


async def test_news_brief_user_config_overrides_default_category() -> None:
    captured: list[tuple[str, int]] = []

    async def fake(category: str, limit: int):
        captured.append((category, limit))
        return []

    w = NewsBriefWidget(_ExtraFetchers(news_brief=fake), category="all", limit=3)
    ctx = _ctx()
    ctx.config = {"category": "tech", "limit": 5}
    await w.render(ctx)
    assert captured[0][0] == "tech"
    assert captured[0][1] == 5


async def test_news_brief_swallows_fetcher_failure() -> None:
    async def boom(_c, _l):
        raise RuntimeError("rss down")
    w = NewsBriefWidget(_ExtraFetchers(news_brief=boom))
    out = await w.render(_ctx())
    assert out.body["items"] == []


async def test_news_brief_no_fetcher_returns_empty() -> None:
    w = NewsBriefWidget(_ExtraFetchers())
    out = await w.render(_ctx())
    assert out.body["items"] == []


# ---------------------------------------------------------------- radio_now_playing


async def test_now_playing_when_active() -> None:
    async def fake():
        return {"title": "Rai Radio 1", "source": "rai.it", "started_unix": 1.0}
    w = RadioNowPlayingWidget(_ExtraFetchers(now_playing=fake))
    out = await w.render(_ctx())
    assert out.body["playing"] is True
    assert out.body["title"] == "Rai Radio 1"


async def test_now_playing_when_silent() -> None:
    async def fake():
        return None
    w = RadioNowPlayingWidget(_ExtraFetchers(now_playing=fake))
    out = await w.render(_ctx())
    assert out.body["playing"] is False


async def test_now_playing_swallows_fetcher_failure() -> None:
    async def boom():
        raise RuntimeError("oops")
    w = RadioNowPlayingWidget(_ExtraFetchers(now_playing=boom))
    out = await w.render(_ctx())
    assert out.body["playing"] is False
