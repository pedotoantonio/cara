"""Unit tests for `cara.workflows.recipe`."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cara.workflows.base import (
    ExecutionResult,
    ProposedAction,
    StructuredData,
    WorkflowInput,
)
from cara.workflows.recipe import (
    RecipeWorkflow,
    find_url,
    looks_like_recipe,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- detection helpers


def test_find_url_finds_https_link() -> None:
    assert find_url("vedi qui https://example.com/ricette/torta") == \
        "https://example.com/ricette/torta"


def test_find_url_returns_none_when_absent() -> None:
    assert find_url("nessun link qui") is None


def test_looks_like_recipe_with_keywords() -> None:
    text = (
        "Ricetta della carbonara classica\n"
        "Ingredienti per 4 persone:\n"
        "- guanciale\n- uova\n- pecorino\n"
        "Preparazione: scaldare la padella…"
    )
    matched, score = looks_like_recipe(text)
    assert matched is True
    assert score >= 0.30


def test_looks_like_recipe_short_text_rejected() -> None:
    matched, score = looks_like_recipe("ciao")
    assert matched is False


def test_looks_like_recipe_random_text_low_score() -> None:
    matched, score = looks_like_recipe(
        "Una poesia di Leopardi parla di luna e infinito senza ingredienti " * 2
    )
    # "ingredienti" is the only marker hit → may still cross threshold.
    # Conservative: simply assert score is low-ish.
    assert score <= 0.5


# ---------------------------------------------------------------- classify


async def test_classify_with_url() -> None:
    wf = RecipeWorkflow()
    inp = WorkflowInput(
        kind="text",
        payload={"text": "trova la ricetta su https://gz.it/torta-margherita"},
    )
    res = await wf.classify(inp)
    assert res.matches is True
    assert res.hints.get("url") == "https://gz.it/torta-margherita"


async def test_classify_with_inline_url_field() -> None:
    wf = RecipeWorkflow()
    inp = WorkflowInput(
        kind="url",
        payload={"url": "https://blog.example.com/pasta"},
    )
    res = await wf.classify(inp)
    assert res.matches is True


async def test_classify_with_ocr_text_recipe() -> None:
    wf = RecipeWorkflow()
    text = (
        "Ricetta - Pane fatto in casa\n"
        "Ingredienti: farina, acqua, lievito, sale\n"
        "Preparazione: impastare, lievitare, cuocere"
    )
    inp = WorkflowInput(kind="image", payload={"ocr_text": text})
    res = await wf.classify(inp)
    assert res.matches is True


async def test_classify_no_text_no_url() -> None:
    wf = RecipeWorkflow()
    res = await wf.classify(WorkflowInput(kind="image", payload={}))
    assert res.matches is False


async def test_classify_low_score_doesnt_match() -> None:
    wf = RecipeWorkflow()
    inp = WorkflowInput(
        kind="text",
        payload={"text": "stamattina ho fatto colazione e poi sono uscito"},
    )
    res = await wf.classify(inp)
    assert res.matches is False


# ---------------------------------------------------------------- extract


async def test_extract_from_url_calls_fetch() -> None:
    captured: list[str] = []

    async def fake_fetch(url: str) -> str:
        captured.append(url)
        return (
            "Ricetta torta\n"
            "Ingredienti:\n- farina\n- uova\n- zucchero\n"
            "Preparazione: …"
        )

    def fake_extract(text: str) -> list[str]:
        return ["farina", "uova", "zucchero"]

    wf = RecipeWorkflow(
        fetch_text=fake_fetch, extract_ingredients=fake_extract,
    )
    inp = WorkflowInput(
        kind="url",
        payload={"url": "https://x/recipe", "user_id": 7},
    )
    data = await wf.extract(inp, hints={"url": "https://x/recipe"})
    assert captured == ["https://x/recipe"]
    assert data.data["ingredients"] == ["farina", "uova", "zucchero"]
    assert data.data["source"] == "url"
    assert data.data["user_id"] == 7


async def test_extract_from_text_skips_fetch() -> None:
    fetch_calls: list[str] = []

    async def fake_fetch(url: str) -> str:
        fetch_calls.append(url)
        return ""

    def fake_extract(text: str) -> list[str]:
        return ["pomodoro", "basilico"]

    wf = RecipeWorkflow(
        fetch_text=fake_fetch, extract_ingredients=fake_extract,
    )
    inp = WorkflowInput(
        kind="image",
        payload={"ocr_text": "Ingredienti pomodoro basilico", "user_id": 1},
    )
    data = await wf.extract(inp, hints={"text": "Ingredienti pomodoro basilico"})
    assert fetch_calls == []
    assert data.data["ingredients"] == ["pomodoro", "basilico"]
    assert data.data["source"] == "text"


async def test_extract_caps_at_max_ingredients() -> None:
    def fake_extract(text: str) -> list[str]:
        return [f"ingrediente_{i}" for i in range(50)]

    wf = RecipeWorkflow(extract_ingredients=fake_extract)
    inp = WorkflowInput(kind="text", payload={"user_id": 1})
    data = await wf.extract(inp, hints={"text": "Ingredienti..."})
    assert data.data["ingredients_count"] == 30  # default cap


async def test_extract_handles_fetch_failure_gracefully() -> None:
    async def fake_fetch(url: str) -> str:  # noqa: ARG001
        raise RuntimeError("network down")

    def fake_extract(text: str) -> list[str]:  # noqa: ARG001
        return []

    wf = RecipeWorkflow(
        fetch_text=fake_fetch, extract_ingredients=fake_extract,
    )
    inp = WorkflowInput(kind="url", payload={"user_id": 1})
    data = await wf.extract(inp, hints={"url": "https://broken/x"})
    # No ingredients extracted, but no exception.
    assert data.data["ingredients"] == []
    assert data.confidence == 0.0


# ---------------------------------------------------------------- propose


async def test_propose_emits_bulk_add() -> None:
    wf = RecipeWorkflow()
    data = StructuredData(
        kind="recipe",
        data={
            "user_id": 1,
            "ingredients": ["farina", "uova", "zucchero"],
            "ingredients_count": 3,
        },
        confidence=0.85,
    )
    actions = await wf.propose(data)
    assert len(actions) == 1
    assert actions[0].tool == "bulk_add_shopping"
    assert actions[0].args["items"] == ["farina", "uova", "zucchero"]


async def test_propose_no_ingredients_no_actions() -> None:
    wf = RecipeWorkflow()
    data = StructuredData(
        kind="recipe",
        data={"user_id": 1, "ingredients": []},
    )
    actions = await wf.propose(data)
    assert actions == []


async def test_propose_no_user_id_no_actions() -> None:
    wf = RecipeWorkflow()
    data = StructuredData(
        kind="recipe",
        data={"user_id": None, "ingredients": ["x"]},
    )
    actions = await wf.propose(data)
    assert actions == []


# ---------------------------------------------------------------- execute


@dataclass
class _FakeShoppingRow:
    id: int = 0


async def test_execute_adds_each_ingredient() -> None:
    seen: list[tuple[int, str]] = []

    async def fake_add(*, user_id: int, title: str):
        seen.append((user_id, title))
        return _FakeShoppingRow(id=len(seen) * 10)

    wf = RecipeWorkflow(add_shopping=fake_add)
    actions = [
        ProposedAction(
            tool="bulk_add_shopping",
            args={"user_id": 1, "items": ["farina", "uova"]},
            summary="x",
        ),
    ]
    results = await wf.execute(actions)
    assert results[0].ok
    assert results[0].output["added_count"] == 2
    assert seen == [(1, "farina"), (1, "uova")]


async def test_execute_partial_failure_reported_in_output() -> None:
    """One ingredient fails to add → still success on the rest."""
    async def fake_add(*, user_id: int, title: str):  # noqa: ARG001
        if title == "uova":
            raise RuntimeError("constraint violation")
        return _FakeShoppingRow(id=42)

    wf = RecipeWorkflow(add_shopping=fake_add)
    actions = [
        ProposedAction(
            tool="bulk_add_shopping",
            args={"user_id": 1, "items": ["farina", "uova", "zucchero"]},
            summary="x",
        ),
    ]
    results = await wf.execute(actions)
    assert results[0].ok
    assert results[0].output["added_count"] == 2
    assert results[0].output["total_requested"] == 3
    assert "errors" in results[0].output


async def test_execute_unknown_tool_marks_failure() -> None:
    wf = RecipeWorkflow()
    actions = [ProposedAction(tool="banana", args={}, summary="x")]
    results = await wf.execute(actions)
    assert results[0].ok is False


async def test_execute_no_adapter_marks_failure() -> None:
    wf = RecipeWorkflow()  # no add_shopping adapter
    actions = [ProposedAction(
        tool="bulk_add_shopping",
        args={"user_id": 1, "items": ["x"]}, summary="x",
    )]
    results = await wf.execute(actions)
    assert results[0].ok is False
    assert "adapter not configured" in (results[0].error or "")
