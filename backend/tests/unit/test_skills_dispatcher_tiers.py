"""Unit tests for the multi-tier skill dispatcher (Phase C).

Tier-1 regex: covered by existing tests; here we just verify it still
hits when no embedder/llm is given.

Tier-2 cosine: stubs the embedder with deterministic vectors so the
test is reproducible and doesn't load the 118 MB sentence-transformers
model.

Tier-3 LLM: stubs the llm_call to return a chosen integer, then asserts
the dispatcher routes to the right skill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from cara.skills import dispatcher as skill_dispatcher


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _FakeEmbedding:
    vector: list[float]


class _FakeEmbedder:
    """Map a fixed dictionary of strings to vectors (1.0 in slot N, 0 else).
    For unknown strings, returns the zero vector — i.e. nothing matches."""

    def __init__(self, mapping: dict[str, int], dim: int = 8) -> None:
        self._mapping = mapping
        self._dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self._dim
        slot = self._mapping.get(text.strip().lower())
        if slot is not None and 0 <= slot < self._dim:
            v[slot] = 1.0
        return v

    async def encode(self, text: str) -> _FakeEmbedding:
        return _FakeEmbedding(self._vec(text))

    async def encode_many(self, texts: list[str]) -> list[_FakeEmbedding]:
        return [_FakeEmbedding(self._vec(t)) for t in texts]


@dataclass
class _FakeSkill:
    """Drop-in replacement for the Skill ORM row when we feed
    `_load_active` directly via cache-injection."""

    id: str
    name: str
    description: str
    intent_examples: list[str]
    slot_extraction: dict[str, Any]
    status: str = "active"


def _inject_cache(skills: list[Any]) -> None:
    """Bypass the SQL load by stuffing the module-level cache."""
    skill_dispatcher._cache = list(skills)
    skill_dispatcher._tier2_index = None


# ---------------------------------------------------------------------------
# Tier-1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier1_regex_match_takes_precedence() -> None:
    sk_regex = _FakeSkill(
        id="r-1", name="add_to_list", description="Aggiungi un articolo alla lista",
        intent_examples=[],
        slot_extraction={
            "item": {"method": "regex", "pattern": r"aggiungi (\w+) alla lista", "group": 1},
        },
    )
    _inject_cache([sk_regex])

    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="aggiungi pasta alla lista",
    )
    assert out is not None
    sk, slots, tier, conf = out
    assert sk.name == "add_to_list"
    assert slots == {"item": "pasta"}
    assert tier == "tier1"
    assert conf == 1.0


@pytest.mark.asyncio
async def test_tier1_no_match_returns_none_when_no_other_tiers() -> None:
    sk = _FakeSkill(
        id="r-2", name="x", description="x",
        intent_examples=[],
        slot_extraction={
            "item": {"method": "regex", "pattern": r"aggiungi (\w+) alla lista"},
        },
    )
    _inject_cache([sk])
    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="che giorno è oggi",
    )
    assert out is None


# ---------------------------------------------------------------------------
# Tier-2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier2_cosine_picks_best_skill() -> None:
    sk_a = _FakeSkill(
        id="a-1", name="ricetta",
        description="Cerca ingredienti di una ricetta",
        intent_examples=["voglio fare una ricetta", "ingredienti per la pasta"],
        slot_extraction={},
    )
    sk_b = _FakeSkill(
        id="b-1", name="meteo",
        description="Previsioni del tempo",
        intent_examples=["che tempo fa", "previsioni meteo"],
        slot_extraction={},
    )
    _inject_cache([sk_a, sk_b])

    embedder = _FakeEmbedder({
        # Skill A intents map to slot 0 (recipe cluster)
        "voglio fare una ricetta": 0,
        "ingredienti per la pasta": 0,
        # Skill B intents map to slot 1 (weather cluster)
        "che tempo fa": 1,
        "previsioni meteo": 1,
        # Test queries
        "cosa serve per la lasagna": 0,   # → ricetta
        "pioverà domani": 1,              # → meteo
    })

    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="cosa serve per la lasagna",
        embedder=embedder, tier2_enabled=True, tier2_threshold=0.5,
    )
    assert out is not None
    sk, _slots, tier, conf = out
    assert sk.name == "ricetta"
    assert tier == "tier2"
    assert conf >= 0.5


@pytest.mark.asyncio
async def test_tier2_skips_skills_with_no_intent_examples() -> None:
    sk_no_examples = _FakeSkill(
        id="x-1", name="hidden", description="hidden",
        intent_examples=[],   # NOT eligible for tier-2
        slot_extraction={},
    )
    _inject_cache([sk_no_examples])
    embedder = _FakeEmbedder({"qualunque cosa": 0})
    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="qualunque cosa",
        embedder=embedder, tier2_enabled=True, tier2_threshold=0.5,
    )
    assert out is None


@pytest.mark.asyncio
async def test_tier2_below_threshold_falls_through() -> None:
    sk = _FakeSkill(
        id="thr-1", name="meteo", description="meteo",
        intent_examples=["che tempo fa"],
        slot_extraction={},
    )
    _inject_cache([sk])
    # Map the message to a different slot than the intent — cosine == 0
    embedder = _FakeEmbedder({
        "che tempo fa": 0,
        "facciamo dieci più dieci": 5,
    })
    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="facciamo dieci più dieci",
        embedder=embedder, tier2_enabled=True, tier2_threshold=0.5,
    )
    assert out is None


@pytest.mark.asyncio
async def test_tier2_index_is_cached_until_invalidated() -> None:
    sk = _FakeSkill(
        id="cache-1", name="x", description="x",
        intent_examples=["ciao"],
        slot_extraction={},
    )
    _inject_cache([sk])

    calls: list[list[str]] = []

    class _CountingEmbedder(_FakeEmbedder):
        async def encode_many(self, texts: list[str]) -> list[_FakeEmbedding]:
            calls.append(list(texts))
            return await super().encode_many(texts)

    embedder = _CountingEmbedder({"ciao": 0, "saluti": 0})

    # First call → index built (1 encode_many for the skill)
    await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="saluti",
        embedder=embedder, tier2_enabled=True, tier2_threshold=0.5,
    )
    assert len(calls) == 1

    # Second call → index reused, no second encode_many
    await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="saluti",
        embedder=embedder, tier2_enabled=True, tier2_threshold=0.5,
    )
    assert len(calls) == 1

    # Invalidate → next call rebuilds
    skill_dispatcher.invalidate_cache()
    _inject_cache([sk])  # repopulate active skills
    await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="saluti",
        embedder=embedder, tier2_enabled=True, tier2_threshold=0.5,
    )
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Tier-3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier3_llm_picks_skill_by_number() -> None:
    sk1 = _FakeSkill(
        id="t3-1", name="alpha", description="prima skill",
        intent_examples=[], slot_extraction={},
    )
    sk2 = _FakeSkill(
        id="t3-2", name="beta", description="seconda skill",
        intent_examples=[], slot_extraction={},
    )
    sk3 = _FakeSkill(
        id="t3-3", name="gamma", description="terza skill",
        intent_examples=[], slot_extraction={},
    )
    _inject_cache([sk1, sk2, sk3])

    async def fake_llm(_prompt: str, _max: int) -> str:
        return "2"

    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="qualcosa di vago",
        embedder=None, llm_call=fake_llm,
        tier2_enabled=False, tier3_enabled=True,
    )
    assert out is not None
    sk, _slots, tier, conf = out
    assert sk.name == "beta"
    assert tier == "tier3"
    assert conf == 1.0


@pytest.mark.asyncio
async def test_tier3_zero_means_no_match() -> None:
    sk = _FakeSkill(
        id="t3-z", name="solo", description="d",
        intent_examples=[], slot_extraction={},
    )
    _inject_cache([sk])

    async def fake_llm(_prompt: str, _max: int) -> str:
        return "0"

    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="totalmente fuori scopo",
        llm_call=fake_llm, tier3_enabled=True,
    )
    assert out is None


@pytest.mark.asyncio
async def test_tier3_garbage_response_returns_none() -> None:
    sk = _FakeSkill(
        id="t3-g", name="solo", description="d",
        intent_examples=[], slot_extraction={},
    )
    _inject_cache([sk])

    async def fake_llm(_prompt: str, _max: int) -> str:
        return "non lo so"

    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="x",
        llm_call=fake_llm, tier3_enabled=True,
    )
    assert out is None


@pytest.mark.asyncio
async def test_tier3_out_of_range_returns_none() -> None:
    sk = _FakeSkill(
        id="t3-r", name="solo", description="d",
        intent_examples=[], slot_extraction={},
    )
    _inject_cache([sk])

    async def fake_llm(_prompt: str, _max: int) -> str:
        # Index 99 doesn't exist (we have 1 skill)
        return "99"

    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="x",
        llm_call=fake_llm, tier3_enabled=True,
    )
    assert out is None


@pytest.mark.asyncio
async def test_tier3_llm_exception_swallowed() -> None:
    sk = _FakeSkill(
        id="t3-e", name="solo", description="d",
        intent_examples=[], slot_extraction={},
    )
    _inject_cache([sk])

    async def boom(_prompt: str, _max: int) -> str:
        raise RuntimeError("LLM offline")

    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="x", llm_call=boom, tier3_enabled=True,
    )
    assert out is None


# ---------------------------------------------------------------------------
# Tier ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier1_wins_over_tier2_even_when_both_match() -> None:
    sk = _FakeSkill(
        id="ord-1", name="x", description="d",
        intent_examples=["ciao mondo"],
        slot_extraction={
            "item": {"method": "regex", "pattern": r"ciao (\w+)", "group": 1},
        },
    )
    _inject_cache([sk])
    embedder = _FakeEmbedder({"ciao mondo": 0})

    out = await skill_dispatcher.match_with_tier(
        session=None,  # type: ignore[arg-type]
        message="ciao mondo",
        embedder=embedder, tier2_enabled=True, tier2_threshold=0.5,
    )
    assert out is not None
    _sk, _slots, tier, _conf = out
    assert tier == "tier1"
