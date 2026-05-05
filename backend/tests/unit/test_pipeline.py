"""Unit tests for `cara.router.pipeline`."""

from __future__ import annotations

import pytest

from cara.router import (
    AlwaysHitStage,
    AlwaysMissStage,
    Hit,
    Miss,
    Pipeline,
    RouteContext,
)


pytestmark = pytest.mark.asyncio


def _ctx(message: str = "ciao") -> RouteContext:
    return RouteContext(user_id=1, message=message)


async def test_empty_pipeline_returns_canonical_empty_miss() -> None:
    p = Pipeline()
    result = await p.route(_ctx())
    assert isinstance(result, Miss)
    assert result.stage_name == "pipeline.empty"
    assert result.reason == "no_stages"


async def test_pipeline_returns_first_hit_and_skips_rest() -> None:
    seen = []

    class RecordingMiss(AlwaysMissStage):
        name = "record_miss"

        async def try_handle(self, ctx):
            seen.append(self.name)
            return await super().try_handle(ctx)

    class RecordingHit(AlwaysHitStage):
        async def try_handle(self, ctx):
            seen.append(self.name)
            return await super().try_handle(ctx)

    p = Pipeline([
        RecordingMiss(reason="too_short"),
        RecordingHit(response="handled", stage_name="hit_a"),
        RecordingHit(response="should_not_reach", stage_name="hit_b"),
    ])
    result = await p.route(_ctx())
    assert isinstance(result, Hit)
    assert result.response == "handled"
    assert result.stage_name == "hit_a"
    # Third stage MUST NOT have been invoked.
    assert seen == ["record_miss", "hit_a"]


async def test_pipeline_returns_last_miss_when_all_decline() -> None:
    p = Pipeline([
        AlwaysMissStage(reason="reason_one"),
        AlwaysMissStage(reason="reason_two"),
    ])
    # Override second stage's name so we can assert which one bottomed out.
    p.stages[1].name = "second"  # type: ignore[attr-defined]
    result = await p.route(_ctx())
    assert isinstance(result, Miss)
    assert result.stage_name == "second"
    assert result.reason == "reason_two"


async def test_stage_exception_does_not_bring_down_pipeline() -> None:
    class BoomStage:
        name = "boom"

        async def try_handle(self, ctx):  # noqa: ARG002
            raise RuntimeError("nope")

    p = Pipeline([BoomStage(), AlwaysHitStage(response="recovered")])
    result = await p.route(_ctx())
    assert isinstance(result, Hit)
    assert result.response == "recovered"


async def test_stage_exception_recorded_as_classified_miss() -> None:
    class BoomStage:
        name = "boom"

        async def try_handle(self, ctx):  # noqa: ARG002
            raise ValueError("bad")

    p = Pipeline([BoomStage()])
    result = await p.route(_ctx())
    assert isinstance(result, Miss)
    assert result.stage_name == "boom"
    assert result.reason == "exception:ValueError"


async def test_telemetry_sink_called_once_per_stage() -> None:
    calls = []

    def sink(stage_name, outcome, reason, duration, ctx):  # noqa: ARG001
        calls.append((stage_name, outcome, reason))

    p = Pipeline(
        [AlwaysMissStage(reason="r1"), AlwaysHitStage()],
        telemetry_sink=sink,
    )
    await p.route(_ctx())
    assert len(calls) == 2
    assert calls[0][1] == "miss"
    assert calls[0][2] == "r1"
    assert calls[1][1] == "hit"


async def test_telemetry_sink_failure_is_swallowed() -> None:
    def sink(*_args, **_kw):
        raise RuntimeError("bad sink")

    p = Pipeline([AlwaysHitStage()], telemetry_sink=sink)
    # Must NOT raise.
    result = await p.route(_ctx())
    assert isinstance(result, Hit)


async def test_add_method_chains() -> None:
    p = Pipeline().add(AlwaysMissStage()).add(AlwaysHitStage())
    assert len(p.stages) == 2
    result = await p.route(_ctx())
    assert isinstance(result, Hit)


async def test_duration_ms_populated_on_hit_and_miss() -> None:
    p = Pipeline([AlwaysMissStage(), AlwaysHitStage()])
    result = await p.route(_ctx())
    assert result.duration_ms >= 0


async def test_route_context_extras_pass_between_stages() -> None:
    class WriterStage:
        name = "writer"

        async def try_handle(self, ctx):
            ctx.extras["from_writer"] = "marker"
            return Miss(stage_name=self.name, reason="just_writing")

    class ReaderStage:
        name = "reader"

        async def try_handle(self, ctx):
            assert ctx.extras.get("from_writer") == "marker"
            return Hit(stage_name=self.name, response="seen_marker")

    p = Pipeline([WriterStage(), ReaderStage()])
    result = await p.route(_ctx())
    assert isinstance(result, Hit)
    assert result.response == "seen_marker"
