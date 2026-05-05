"""Unit tests for `cara.workflows` infrastructure (registry + protocol)."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from cara.workflows import (
    ClassifyResult,
    ExecutionResult,
    ProposedAction,
    StructuredData,
    Workflow,
    WorkflowInput,
    WorkflowRegistry,
    get_default_registry,
)
from cara.workflows.base import reset_default_registry_for_test

# pytestmark intentionally NOT pytest.mark.asyncio at module scope:
# protocol/dataclass tests below are sync. Async tests run under the
# pytest-asyncio auto mode set in pyproject.toml.


# ---------------------------------------------------------------- helper concrete workflow


class _DummyWorkflow:
    """Minimal concrete workflow for registry tests."""

    name = "dummy"
    version = "0.1"

    def __init__(
        self,
        *,
        name: str = "dummy",
        match: bool = True,
        confidence: float = 1.0,
        classify_raises: bool = False,
    ) -> None:
        self.name = name
        self._match = match
        self._confidence = confidence
        self._raise = classify_raises
        self.calls = {"classify": 0, "extract": 0, "propose": 0, "execute": 0}

    async def classify(self, inp: WorkflowInput) -> ClassifyResult:
        self.calls["classify"] += 1
        if self._raise:
            raise RuntimeError("boom")
        return ClassifyResult(
            matches=self._match, confidence=self._confidence, reason="dummy"
        )

    async def extract(self, inp: WorkflowInput, hints: dict) -> StructuredData:
        self.calls["extract"] += 1
        return StructuredData(kind="dummy", data={"got": True}, confidence=0.9)

    async def propose(self, data: StructuredData) -> list[ProposedAction]:
        self.calls["propose"] += 1
        return [ProposedAction(tool="add_task", args={"title": "x"}, summary="x")]

    async def execute(
        self, actions: Iterable[ProposedAction]
    ) -> list[ExecutionResult]:
        self.calls["execute"] += 1
        return [ExecutionResult.success(a) for a in actions]


# ---------------------------------------------------------------- ProposedAction


def test_proposed_action_to_dict_round_trip() -> None:
    a = ProposedAction(tool="add_task", args={"title": "x"}, summary="add x")
    d = a.to_dict()
    assert d["tool"] == "add_task"
    assert d["args"]["title"] == "x"
    assert d["reversible"] is True


def test_execution_result_helpers() -> None:
    a = ProposedAction(tool="add_task", args={}, summary="x")
    s = ExecutionResult.success(a, output={"id": 7})
    f = ExecutionResult.failure(a, error="db down")
    assert s.ok is True and s.output["id"] == 7
    assert f.ok is False and f.error == "db down"


# ---------------------------------------------------------------- registry


async def test_registry_register_and_list_in_order() -> None:
    reg = WorkflowRegistry()
    reg.register(_DummyWorkflow(name="a"))
    reg.register(_DummyWorkflow(name="b"))
    assert [w.name for w in reg.list()] == ["a", "b"]


async def test_registry_register_replaces_same_name() -> None:
    """Registering twice with the same name replaces — no duplicates."""
    reg = WorkflowRegistry()
    reg.register(_DummyWorkflow(name="a"))
    reg.register(_DummyWorkflow(name="a"))
    assert len(reg.list()) == 1


async def test_registry_unregister_drops_workflow() -> None:
    reg = WorkflowRegistry()
    reg.register(_DummyWorkflow(name="a"))
    reg.unregister("a")
    assert reg.list() == []


async def test_registry_classify_returns_first_match_in_order() -> None:
    reg = WorkflowRegistry()
    miss = _DummyWorkflow(name="miss", match=False)
    hit = _DummyWorkflow(name="hit", match=True, confidence=0.9)
    other = _DummyWorkflow(name="other", match=True, confidence=0.95)
    reg.register(miss)
    reg.register(hit)
    reg.register(other)

    inp = WorkflowInput(kind="image", payload={})
    result = await reg.classify_first_match(inp)
    assert result is not None
    workflow, classify_result = result
    assert workflow.name == "hit"  # first match wins, even if 'other' has higher confidence
    assert classify_result.matches is True
    # 'miss' was probed but not 'other' (short-circuit at first hit).
    assert miss.calls["classify"] == 1
    assert hit.calls["classify"] == 1
    assert other.calls["classify"] == 0


async def test_registry_classify_skips_disabled() -> None:
    reg = WorkflowRegistry()
    a = _DummyWorkflow(name="a", match=True, confidence=0.9)
    b = _DummyWorkflow(name="b", match=True, confidence=0.9)
    reg.register(a)
    reg.register(b)
    reg.set_enabled("a", False)

    result = await reg.classify_first_match(WorkflowInput(kind="image"))
    assert result is not None
    workflow, _ = result
    assert workflow.name == "b"
    assert a.calls["classify"] == 0


async def test_registry_classify_respects_min_confidence() -> None:
    reg = WorkflowRegistry()
    low = _DummyWorkflow(name="low", match=True, confidence=0.4)
    reg.register(low)

    inp = WorkflowInput(kind="image")
    assert await reg.classify_first_match(inp, min_confidence=0.5) is None


async def test_registry_classify_swallows_workflow_exception() -> None:
    """A buggy classify() must NOT poison the registry — try the next one."""
    reg = WorkflowRegistry()
    bad = _DummyWorkflow(name="bad", classify_raises=True)
    good = _DummyWorkflow(name="good", match=True, confidence=0.9)
    reg.register(bad)
    reg.register(good)

    result = await reg.classify_first_match(WorkflowInput(kind="image"))
    assert result is not None
    assert result[0].name == "good"


async def test_registry_returns_none_when_no_match() -> None:
    reg = WorkflowRegistry()
    reg.register(_DummyWorkflow(name="m", match=False))
    assert await reg.classify_first_match(WorkflowInput(kind="image")) is None


def test_registry_enabled_state_default_true() -> None:
    reg = WorkflowRegistry()
    reg.register(_DummyWorkflow(name="x"))
    assert reg.is_enabled("x") is True
    reg.set_enabled("x", False)
    assert reg.is_enabled("x") is False


# ---------------------------------------------------------------- default singleton


def test_default_registry_is_a_singleton() -> None:
    reset_default_registry_for_test()
    a = get_default_registry()
    b = get_default_registry()
    assert a is b


def test_default_registry_reset_clears_state() -> None:
    reset_default_registry_for_test()
    reg = get_default_registry()
    reg.register(_DummyWorkflow(name="x"))
    reset_default_registry_for_test()
    new_reg = get_default_registry()
    assert new_reg is not reg
    assert new_reg.list() == []


# ---------------------------------------------------------------- Workflow protocol


def test_dummy_workflow_satisfies_protocol() -> None:
    """Concrete workflows ducktype Workflow at runtime."""
    w = _DummyWorkflow()
    assert isinstance(w, Workflow)


# ---------------------------------------------------------------- four-phase orchestration


async def test_four_phases_invocable_separately() -> None:
    """Each phase is independently testable."""
    w = _DummyWorkflow()
    inp = WorkflowInput(kind="image", payload={"file_id": "abc"}, user_id=1)

    classify_result = await w.classify(inp)
    assert classify_result.matches

    extracted = await w.extract(inp, classify_result.hints)
    assert extracted.kind == "dummy"
    assert extracted.data["got"] is True

    proposed = await w.propose(extracted)
    assert len(proposed) == 1

    results = await w.execute(proposed)
    assert all(r.ok for r in results)
