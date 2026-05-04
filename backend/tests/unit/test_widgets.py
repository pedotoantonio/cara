"""Unit tests for the widget engine + catalog."""

from __future__ import annotations

import time

import pytest

from cara.widgets import (
    Widget,
    WidgetContext,
    WidgetData,
    WidgetError,
    WidgetRegistry,
    WidgetSize,
)
from cara.widgets.catalog import (
    NoteBrief,
    NotesRecentWidget,
    PresenceBrief,
    PresenceWidget,
    QuickActionsWidget,
    ShoppingBrief,
    ShoppingQuickWidget,
    TaskBrief,
    TasksMineWidget,
    TodaySummaryWidget,
    WeatherBrief,
    WeatherNowWidget,
    _Fetchers,
    register_all,
)


pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------- registry


def _ctx(user_id: int = 1, role: str = "parent") -> WidgetContext:
    return WidgetContext(user_id=user_id, user_role=role)


class _StubWidget:
    """Minimal Widget for registry/protocol tests."""
    def __init__(self, wid: str = "stub", roles=()) -> None:
        self.id = wid
        self.title_default = "Stub"
        self.refresh_interval_s = 60
        self.available_for_roles: tuple[str, ...] = roles

    async def render(self, ctx, *, size=WidgetSize.MEDIUM):  # noqa: ARG002
        return WidgetData(widget_id=self.id, title=self.title_default,
                          kind="metric", body={"v": 1})


async def test_registry_register_and_get() -> None:
    reg = WidgetRegistry()
    reg.register(_StubWidget("a"))
    reg.register(_StubWidget("b"))
    assert [w.id for w in reg.list()] == ["a", "b"]
    assert reg.get("a") is not None
    assert reg.get("missing") is None


async def test_registry_register_replaces_same_id() -> None:
    reg = WidgetRegistry()
    reg.register(_StubWidget("a"))
    reg.register(_StubWidget("a"))
    assert len(reg.list()) == 1


async def test_registry_unregister() -> None:
    reg = WidgetRegistry()
    reg.register(_StubWidget("a"))
    reg.unregister("a")
    assert reg.list() == []


async def test_registry_available_for_filters_by_role() -> None:
    reg = WidgetRegistry()
    reg.register(_StubWidget("everyone", roles=()))
    reg.register(_StubWidget("parents_only", roles=("parent",)))
    parent_widgets = {w.id for w in reg.available_for("parent")}
    teen_widgets = {w.id for w in reg.available_for("teen")}
    assert parent_widgets == {"everyone", "parents_only"}
    assert teen_widgets == {"everyone"}


async def test_render_many_returns_in_requested_order() -> None:
    reg = WidgetRegistry()
    reg.register(_StubWidget("x"))
    reg.register(_StubWidget("y"))
    out = await reg.render_many(["y", "x"], _ctx())
    assert [d.widget_id for d in out] == ["y", "x"]


async def test_render_many_unknown_widget_yields_error_payload() -> None:
    reg = WidgetRegistry()
    out = await reg.render_many(["does_not_exist"], _ctx())
    assert out[0].error is not None
    assert out[0].kind == "error"


async def test_render_many_widget_exception_is_isolated() -> None:
    """A buggy widget MUST NOT bring down the dashboard."""
    class BoomWidget:
        id = "boom"
        title_default = "Boom"
        refresh_interval_s = 60
        available_for_roles: tuple[str, ...] = ()

        async def render(self, ctx, *, size=WidgetSize.MEDIUM):  # noqa: ARG002
            raise RuntimeError("kaboom")

    reg = WidgetRegistry()
    reg.register(BoomWidget())
    reg.register(_StubWidget("ok"))

    out = await reg.render_many(["boom", "ok"], _ctx())
    assert out[0].kind == "error"
    assert out[1].kind == "metric"  # unaffected by boom


async def test_render_many_widgeterror_carries_message() -> None:
    """WidgetError surfaces its message to the user (no internal details)."""
    class FriendlyFailWidget:
        id = "ff"
        title_default = "FF"
        refresh_interval_s = 60
        available_for_roles: tuple[str, ...] = ()

        async def render(self, ctx, *, size=WidgetSize.MEDIUM):  # noqa: ARG002
            raise WidgetError("dati non disponibili al momento")

    reg = WidgetRegistry()
    reg.register(FriendlyFailWidget())
    out = await reg.render_many(["ff"], _ctx())
    assert out[0].error == "dati non disponibili al momento"


# --------------------------------------------------------------- catalog: TodaySummary


async def test_today_summary_counts_due_in_24h() -> None:
    now = time.time()
    tasks = [
        TaskBrief("a", "today", done=False, due_unix=now + 3600),
        TaskBrief("b", "later", done=False, due_unix=now + 86400 * 5),
        TaskBrief("c", "done", done=True, due_unix=now),
        TaskBrief("d", "no due", done=False, due_unix=None),
    ]

    async def tasks_for(_uid):
        return tasks

    f = _Fetchers(tasks_for=tasks_for)
    out = await TodaySummaryWidget(f).render(_ctx())
    assert out.body["tasks_today"] == 1


async def test_today_summary_handles_missing_fetchers() -> None:
    """All fetchers None → safe empty body."""
    out = await TodaySummaryWidget(_Fetchers()).render(_ctx())
    assert out.body["tasks_today"] == 0
    assert out.body["weather"] is None
    assert out.body["present_count"] == 0


# --------------------------------------------------------------- catalog: TasksMine


async def test_tasks_mine_top_n_sorted_by_due() -> None:
    now = time.time()
    tasks = [
        TaskBrief("a", "later", done=False, due_unix=now + 86400),
        TaskBrief("b", "today", done=False, due_unix=now + 3600),
        TaskBrief("c", "done", done=True, due_unix=now),
        TaskBrief("d", "no due", done=False, due_unix=None),
    ]

    async def tasks_for(_uid):
        return tasks

    out = await TasksMineWidget(_Fetchers(tasks_for=tasks_for)).render(
        _ctx(), size=WidgetSize.MEDIUM,
    )
    items = out.body["items"]
    # "today" first, "later" second, "no due" last; "done" excluded.
    assert [i["title"] for i in items] == ["today", "later", "no due"]
    assert all(not i["done"] for i in items)


async def test_tasks_mine_small_size_limits_to_3() -> None:
    now = time.time()
    tasks = [
        TaskBrief(str(i), f"t{i}", done=False, due_unix=now + i)
        for i in range(10)
    ]

    async def tasks_for(_uid):
        return tasks

    out = await TasksMineWidget(_Fetchers(tasks_for=tasks_for)).render(
        _ctx(), size=WidgetSize.SMALL,
    )
    assert len(out.body["items"]) == 3


# --------------------------------------------------------------- catalog: ShoppingQuick


async def test_shopping_quick_filters_unchecked_and_caps_six() -> None:
    items = [
        ShoppingBrief(i, f"item{i}", qty=None, bought=False) for i in range(10)
    ] + [
        ShoppingBrief(99, "done", qty=None, bought=True),
    ]

    async def shopping_for(_uid):
        return items

    out = await ShoppingQuickWidget(_Fetchers(shopping_for=shopping_for)).render(_ctx())
    titles = [i["title"] for i in out.body["items"]]
    assert "done" not in titles
    assert len(titles) == 6


# --------------------------------------------------------------- catalog: NotesRecent


async def test_notes_recent_top_3_by_updated() -> None:
    now = time.time()
    notes = [
        NoteBrief(1, "old", "x", updated_unix=now - 1000),
        NoteBrief(2, "newest", "x", updated_unix=now),
        NoteBrief(3, "mid", "x", updated_unix=now - 500),
        NoteBrief(4, "ancient", "x", updated_unix=now - 5000),
    ]

    async def notes_for(_uid):
        return notes

    out = await NotesRecentWidget(_Fetchers(notes_for=notes_for)).render(_ctx())
    titles = [i["title"] for i in out.body["items"]]
    assert titles == ["newest", "mid", "old"]


# --------------------------------------------------------------- catalog: WeatherNow


async def test_weather_now_round_trip() -> None:
    async def weather_for(_uid):
        return WeatherBrief(
            temperature_c=22.49, label="Sereno", icon_slug="sun", is_day=True,
        )

    out = await WeatherNowWidget(_Fetchers(weather_for=weather_for)).render(_ctx())
    assert out.body["available"] is True
    assert out.body["temperature_c"] == 22.5  # rounded
    assert out.body["icon_slug"] == "sun"


async def test_weather_now_unavailable_when_no_data() -> None:
    out = await WeatherNowWidget(_Fetchers()).render(_ctx())
    assert out.body["available"] is False


# --------------------------------------------------------------- catalog: Presence


async def test_presence_widget_lists_people() -> None:
    async def presence():
        return [
            PresenceBrief("Antonio", time.time() - 60),
            PresenceBrief("Sara", time.time() - 30),
        ]

    out = await PresenceWidget(_Fetchers(presence=presence)).render(_ctx())
    assert out.body["count"] == 2
    names = [p["name"] for p in out.body["people"]]
    assert "Antonio" in names and "Sara" in names


# --------------------------------------------------------------- catalog: QuickActions


async def test_quick_actions_default_set() -> None:
    out = await QuickActionsWidget().render(_ctx())
    assert out.kind == "action_grid"
    actions = out.body["actions"]
    assert any(a["id"] == "add_task" for a in actions)


async def test_quick_actions_user_config_overrides_defaults() -> None:
    ctx = WidgetContext(
        user_id=1,
        config={"actions": [{"id": "x", "label": "Custom", "icon": "star"}]},
    )
    out = await QuickActionsWidget().render(ctx)
    assert out.body["actions"] == [{"id": "x", "label": "Custom", "icon": "star"}]


async def test_quick_actions_caps_for_watch_surface() -> None:
    ctx = WidgetContext(user_id=1, surface_class="watch")
    out = await QuickActionsWidget().render(ctx)
    assert len(out.body["actions"]) <= 2


# --------------------------------------------------------------- register_all


async def test_register_all_registers_all_widgets() -> None:
    f = _Fetchers()
    reg = WidgetRegistry()
    register_all(f, registry=reg)
    ids = {w.id for w in reg.list()}
    assert ids == {
        "today_summary", "tasks_mine", "shopping_quick", "notes_recent",
        "weather_now", "presence", "quick_actions",
    }


# --------------------------------------------------------------- WidgetData


async def test_widget_data_to_dict() -> None:
    d = WidgetData(widget_id="x", title="X", kind="metric", body={"v": 1})
    out = d.to_dict()
    assert out["widget_id"] == "x"
    assert out["body"]["v"] == 1
    assert out["error"] is None
