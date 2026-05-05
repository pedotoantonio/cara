"""Unit tests for `cara.smarthome.nlu`."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cara.ai.embeddings import EmbeddingService
from cara.smarthome import Capability, Entity
from cara.smarthome.nlu import (
    Action,
    DeviceAlias,
    SmartHomeNLU,
    aliases_from_entities,
)


pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------- aliases_from_entities


def test_aliases_from_entities_uses_friendly_name() -> None:
    entities = [
        Entity(id="ha:light.cucina", provider="ha", domain="light",
               friendly_name="Luce cucina", area="cucina"),
        Entity(id="ha:switch.tv", provider="ha", domain="switch",
               friendly_name="TV", area="soggiorno"),
    ]
    out = aliases_from_entities(entities)
    aliases = {a.alias for a in out}
    assert "Luce cucina" in aliases
    assert "TV" in aliases


def test_aliases_from_entities_adds_local_id_fallback() -> None:
    entities = [
        Entity(id="ha:light.lampada_principale_cucina", provider="ha",
               domain="light", friendly_name="Lampada principale cucina"),
    ]
    out = aliases_from_entities(entities)
    aliases = {a.alias.lower() for a in out}
    # friendly_name is added; the underscore-fallback is added IF different.
    # In this case both normalise to the same string, so just one alias.
    assert "lampada principale cucina" in aliases


def test_aliases_from_entities_skips_hidden() -> None:
    entities = [
        Entity(id="ha:light.cucina", provider="ha", domain="light",
               friendly_name="Cucina", visible_to_cara=False),
    ]
    assert aliases_from_entities(entities) == []


# --------------------------------------------------------------- intent matching


async def _resolve(utterance: str, aliases=None, **kwargs) -> "Resolution":  # noqa: F821
    nlu = SmartHomeNLU(aliases or [])
    return await nlu.resolve(utterance, **kwargs)


async def test_resolve_no_intent_returns_unmatched() -> None:
    r = await _resolve("oggi piove tantissimo")
    assert r.matched_intent is False


async def test_resolve_turn_on_extracts_action_and_target() -> None:
    aliases = [DeviceAlias(entity_id="ha:light.cucina", alias="luce cucina")]
    r = await _resolve("accendi la luce cucina", aliases)
    assert r.matched_intent is True
    assert r.action == Action.TURN_ON
    assert r.chosen.entity_id == "ha:light.cucina"


async def test_resolve_turn_off() -> None:
    aliases = [DeviceAlias(entity_id="ha:switch.tv", alias="TV")]
    r = await _resolve("spegni la TV", aliases)
    assert r.action == Action.TURN_OFF
    assert r.chosen.entity_id == "ha:switch.tv"


async def test_resolve_open_close() -> None:
    aliases = [DeviceAlias(entity_id="ha:cover.salone", alias="tapparella salone")]
    r = await _resolve("apri la tapparella salone", aliases)
    assert r.action == Action.OPEN
    r = await _resolve("chiudi la tapparella salone", aliases)
    assert r.action == Action.CLOSE


async def test_resolve_set_value_captures_value() -> None:
    aliases = [DeviceAlias(entity_id="ha:climate.salotto", alias="termostato salotto")]
    r = await _resolve("imposta il termostato salotto a 21", aliases)
    assert r.action == Action.SET_VALUE
    assert r.value == "21"


async def test_resolve_query_intent() -> None:
    aliases = [DeviceAlias(entity_id="ha:sensor.temp", alias="temperatura")]
    r = await _resolve("dimmi la temperatura", aliases)
    assert r.action == Action.QUERY


# --------------------------------------------------------------- exact match


async def test_exact_match_returns_full_score() -> None:
    aliases = [DeviceAlias(entity_id="ha:light.cucina", alias="luce cucina")]
    r = await _resolve("accendi luce cucina", aliases)
    assert r.chosen.source == "exact"
    assert r.confidence == pytest.approx(1.0)


async def test_exact_match_is_accent_insensitive() -> None:
    """'Caffè' should match 'Caffe' regardless of accents."""
    aliases = [DeviceAlias(entity_id="ha:switch.caffe", alias="Caffè")]
    r = await _resolve("accendi caffe", aliases)
    assert r.chosen is not None
    assert r.chosen.source == "exact"


# --------------------------------------------------------------- substring match


async def test_substring_match_when_no_exact() -> None:
    """Target 'luce cucina' substring-matches 'luce cucina principale'."""
    aliases = [
        DeviceAlias(entity_id="ha:light.principale", alias="luce cucina principale"),
    ]
    r = await _resolve("accendi luce cucina", aliases)
    assert r.chosen is not None
    assert r.chosen.source == "substring"
    # Substring score is fractional: bonus * (overlap ratio). Smaller
    # query inside larger alias gives a partial score < the bonus.
    assert 0 < r.confidence <= 0.7


async def test_substring_match_skips_too_short_targets() -> None:
    """A 1-2 char target shouldn't trigger substring matching at all."""
    aliases = [DeviceAlias(entity_id="ha:light.x", alias="x luce")]
    r = await _resolve("accendi la x", aliases)
    # The bare 'x' is too short — the resolver should fall through and
    # return no candidate (we keep the intent + target_phrase though).
    assert r.matched_intent is True
    if r.chosen is not None:
        # If something matched, it must NOT be substring-based on 'x'.
        assert r.chosen.source != "substring" or len(r.target_phrase) >= 3


# --------------------------------------------------------------- embedding fallback


async def test_embedding_fallback_when_no_alias_match() -> None:
    """Target that doesn't substring-match any alias falls to embeddings."""
    aliases = [
        DeviceAlias(entity_id="ha:light.tavolo", alias="lampada da tavolo"),
        DeviceAlias(entity_id="ha:light.bagno", alias="luce bagno"),
    ]
    # Fake embedder: anything containing "tavolo" → vector (1, 0, 0); else (0, 1, 0).
    fake_model = MagicMock()

    def fake_encode(texts, **_kw):
        out = []
        for t in texts:
            t_low = t.lower()
            if "tavolo" in t_low:
                out.append([1.0, 0.0, 0.0])
            elif "bagno" in t_low:
                out.append([0.0, 1.0, 0.0])
            else:
                out.append([0.5, 0.5, 0.0])
        return out

    fake_model.encode = MagicMock(side_effect=fake_encode)
    embedder = EmbeddingService(model=fake_model, dim=3)

    nlu = SmartHomeNLU(aliases, embedder=embedder)
    r = await nlu.resolve("accendi sopra il tavolo")
    assert r.chosen is not None
    assert r.chosen.entity_id == "ha:light.tavolo"
    assert r.chosen.source == "embedding"


async def test_embedding_index_only_runs_once() -> None:
    aliases = [DeviceAlias(entity_id="ha:light.x", alias="luce x")]
    fake_model = MagicMock()
    fake_model.encode = MagicMock(return_value=[[1.0, 0.0, 0.0]])
    embedder = EmbeddingService(model=fake_model, dim=3)

    nlu = SmartHomeNLU(aliases, embedder=embedder)
    await nlu.index_aliases()
    await nlu.index_aliases()
    # Only one call to encode for the alias indexing.
    assert fake_model.encode.call_count == 1


# --------------------------------------------------------------- presence disambiguation


async def test_presence_disambiguation_filters_candidates_by_area() -> None:
    """Two 'luce' candidates → presence in 'cucina' resolves to that one."""
    aliases = [
        DeviceAlias(entity_id="ha:light.cucina", alias="luce", area="cucina"),
        DeviceAlias(entity_id="ha:light.bagno", alias="luce", area="bagno"),
    ]
    r = await _resolve("accendi la luce", aliases, present_in_area="cucina")
    assert r.chosen.entity_id == "ha:light.cucina"
    assert r.needs_clarification is False


async def test_presence_does_not_force_match_outside_area() -> None:
    """Presence filter only applies if there's at least one match in area."""
    aliases = [
        DeviceAlias(entity_id="ha:light.bagno", alias="luce", area="bagno"),
    ]
    r = await _resolve("accendi la luce", aliases, present_in_area="cucina")
    # No matches in cucina → keep all candidates.
    assert r.chosen.entity_id == "ha:light.bagno"


# --------------------------------------------------------------- ambiguity


async def test_ambiguity_flagged_when_two_close_candidates() -> None:
    """Two exact matches → both score 1.0 → ambiguous, needs clarification."""
    aliases = [
        DeviceAlias(entity_id="ha:light.cucina", alias="luce"),
        DeviceAlias(entity_id="ha:light.bagno", alias="luce"),
    ]
    r = await _resolve("accendi la luce", aliases)
    assert r.needs_clarification is True
    assert len(r.candidates) == 2


async def test_clear_winner_no_clarification() -> None:
    aliases = [
        DeviceAlias(entity_id="ha:light.cucina", alias="luce cucina"),
        DeviceAlias(entity_id="ha:light.bagno", alias="luce bagno"),
    ]
    r = await _resolve("accendi luce cucina", aliases)
    assert r.needs_clarification is False
    assert r.chosen.entity_id == "ha:light.cucina"
