"""Unit tests for `cara.learning.reflective`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from cara.ai.embeddings import EmbeddingService
from cara.learning import episodic, reflective
from cara.learning.reflective import (
    FailureCluster,
    MissCluster,
    _suggest_pattern,
    detect_router_miss_clusters,
    detect_tool_failure_clusters,
    run_weekly,
)
from cara.learning.tool_metrics import (
    ERROR_MISSING_ARG,
    ERROR_PARSE_TYPO_PREFIX,
    ERROR_UNKNOWN_TOOL,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- _suggest_pattern (sync)


def test_suggest_pattern_shared_tokens() -> None:
    msgs = [
        "metti la radio jazz",
        "metti la radio rock",
        "metti la radio classica",
    ]
    p = _suggest_pattern(msgs)
    assert p is not None
    # Pattern should reference 'metti', 'la', 'radio'.
    assert "metti" in p and "radio" in p


def test_suggest_pattern_returns_none_when_no_overlap() -> None:
    msgs = ["accendi luce", "spegni TV"]
    assert _suggest_pattern(msgs) is None


def test_suggest_pattern_handles_single_message() -> None:
    assert _suggest_pattern(["solo uno"]) is None


# ---------------------------------------------------------------- helpers


async def _seed_user(db_session, uid: int):
    from cara.models.user import User

    u = User(id=uid, email=f"u{uid}@example.com", password_hash="x",
             full_name=None, is_admin=False, is_active=True, role="parent")
    db_session.add(u)
    await db_session.flush()
    return u


def _build_embedder(vector_for_text):
    """Build an EmbeddingService with a fake model whose encode returns
    a deterministic vector per text."""
    fake_model = MagicMock()

    def fake_encode(texts, **_kw):
        return [vector_for_text(t) for t in texts]

    fake_model.encode = MagicMock(side_effect=fake_encode)
    return EmbeddingService(model=fake_model, dim=3)


# ---------------------------------------------------------------- router-miss clustering


async def test_miss_clusters_groups_similar_messages(db_session) -> None:
    """3 'metti la radio X' messages → one cluster of size 3."""
    await _seed_user(db_session, 1)
    for msg in ("metti la radio jazz", "metti la radio rock", "metti la radio classica"):
        await episodic.record(
            db_session, kind="router.miss", user_id=1,
            payload={"message": msg, "stage": "intent_router"},
        )
    await db_session.commit()

    # All three texts contain the word "radio" → embedder collapses to
    # the same vector, similarity 1.0, single cluster.
    def vec(text):
        return [1.0, 0.0, 0.0] if "radio" in text.lower() else [0.0, 1.0, 0.0]

    embedder = _build_embedder(vec)

    clusters = await detect_router_miss_clusters(
        db_session, embedder=embedder,
        since=datetime.now(timezone.utc) - timedelta(days=30),
    )
    assert len(clusters) == 1
    assert clusters[0].size == 3
    assert clusters[0].centroid_message in {
        "metti la radio jazz", "metti la radio rock", "metti la radio classica"
    }
    # Suggested pattern from longest-common-tokens.
    assert clusters[0].suggested_pattern is not None
    assert "radio" in clusters[0].suggested_pattern


async def test_miss_clusters_below_threshold_dropped(db_session) -> None:
    """Only 2 similar messages — below default min_cluster_size=3."""
    await _seed_user(db_session, 1)
    for msg in ("foo bar baz", "foo bar baz"):
        await episodic.record(
            db_session, kind="router.miss", user_id=1, payload={"message": msg},
        )
    await db_session.commit()

    embedder = _build_embedder(lambda _t: [1.0, 0.0, 0.0])
    clusters = await detect_router_miss_clusters(
        db_session, embedder=embedder, min_cluster_size=3,
    )
    assert clusters == []


async def test_miss_clusters_skip_payloads_without_message(db_session) -> None:
    """Old log shape without `message` key → skipped, not crashed."""
    await _seed_user(db_session, 1)
    await episodic.record(db_session, kind="router.miss", user_id=1, payload={})
    await episodic.record(db_session, kind="router.miss", user_id=1,
                           payload={"other_field": "x"})
    await db_session.commit()

    embedder = _build_embedder(lambda _t: [1.0, 0.0, 0.0])
    clusters = await detect_router_miss_clusters(
        db_session, embedder=embedder, min_cluster_size=1,
    )
    assert clusters == []


async def test_miss_clusters_separates_dissimilar_groups(db_session) -> None:
    """Two distinct topics → two clusters."""
    await _seed_user(db_session, 1)
    for msg in ("metti la radio jazz", "metti la radio rock", "metti la radio classica"):
        await episodic.record(
            db_session, kind="router.miss", user_id=1, payload={"message": msg},
        )
    for msg in ("apri la finestra cucina", "apri la finestra salone", "apri la finestra bagno"):
        await episodic.record(
            db_session, kind="router.miss", user_id=1, payload={"message": msg},
        )
    await db_session.commit()

    def vec(t):
        return [1.0, 0.0, 0.0] if "radio" in t else [0.0, 1.0, 0.0]
    embedder = _build_embedder(vec)

    clusters = await detect_router_miss_clusters(
        db_session, embedder=embedder, min_cluster_size=3,
    )
    assert len(clusters) == 2
    sizes = sorted(c.size for c in clusters)
    assert sizes == [3, 3]


async def test_miss_clusters_records_user_ids(db_session) -> None:
    """User ids of every cluster member are aggregated, deduped, sorted."""
    await _seed_user(db_session, 1)
    await _seed_user(db_session, 2)
    await episodic.record(db_session, kind="router.miss", user_id=1,
                           payload={"message": "radio jazz"})
    await episodic.record(db_session, kind="router.miss", user_id=2,
                           payload={"message": "radio rock"})
    await episodic.record(db_session, kind="router.miss", user_id=1,
                           payload={"message": "radio classica"})
    await db_session.commit()

    embedder = _build_embedder(lambda _t: [1.0, 0.0, 0.0])
    clusters = await detect_router_miss_clusters(
        db_session, embedder=embedder, min_cluster_size=3,
    )
    assert clusters and clusters[0].user_ids == [1, 2]


# ---------------------------------------------------------------- tool-failure clustering


async def test_tool_failure_clusters_group_by_error_class(db_session) -> None:
    from cara.learning import tool_metrics

    for _ in range(4):
        await tool_metrics.record_attempt(
            db_session, parse_ok=False, tool_name="add_task",
            error_class=ERROR_PARSE_TYPO_PREFIX,
            raw_call="TUTOOL: add_task(...)",
        )
    for _ in range(2):
        await tool_metrics.record_attempt(
            db_session, parse_ok=True, name_match=False,
            tool_name="play_radio", error_class=ERROR_UNKNOWN_TOOL,
            raw_call="TOOL: playRadiojazz(...)",
        )
    await db_session.commit()

    clusters = await detect_tool_failure_clusters(db_session, min_cluster_size=3)
    assert len(clusters) == 1
    c = clusters[0]
    assert c.error_class == ERROR_PARSE_TYPO_PREFIX
    assert c.count == 4
    assert c.sample_calls  # at least one truncated raw_call retained
    assert "add_task" in c.affected_tools


async def test_tool_failure_clusters_below_threshold_dropped(db_session) -> None:
    from cara.learning import tool_metrics

    for _ in range(2):
        await tool_metrics.record_attempt(
            db_session, parse_ok=False, error_class=ERROR_PARSE_TYPO_PREFIX,
        )
    await db_session.commit()

    clusters = await detect_tool_failure_clusters(db_session, min_cluster_size=3)
    assert clusters == []


async def test_tool_failure_clusters_excludes_executed(db_session) -> None:
    """Successful executions, even if they have a non-null error_class
    by mistake, are excluded — we only cluster real failures."""
    from cara.learning import tool_metrics

    await tool_metrics.record_attempt(
        db_session, parse_ok=True, name_match=True, args_valid=True, executed=True,
        tool_name="add_task",
    )
    for _ in range(3):
        await tool_metrics.record_attempt(
            db_session, parse_ok=True, name_match=True, args_valid=False,
            tool_name="add_task", error_class=ERROR_MISSING_ARG,
        )
    await db_session.commit()

    clusters = await detect_tool_failure_clusters(db_session, min_cluster_size=3)
    assert len(clusters) == 1
    assert clusters[0].count == 3


async def test_tool_failure_clusters_sorted_by_count_desc(db_session) -> None:
    from cara.learning import tool_metrics

    for _ in range(5):
        await tool_metrics.record_attempt(
            db_session, parse_ok=True, name_match=False,
            error_class=ERROR_UNKNOWN_TOOL,
        )
    for _ in range(3):
        await tool_metrics.record_attempt(
            db_session, parse_ok=False, error_class=ERROR_PARSE_TYPO_PREFIX,
        )
    await db_session.commit()

    clusters = await detect_tool_failure_clusters(db_session, min_cluster_size=3)
    assert [c.error_class for c in clusters] == [
        ERROR_UNKNOWN_TOOL, ERROR_PARSE_TYPO_PREFIX
    ]


# ---------------------------------------------------------------- run_weekly


async def test_run_weekly_returns_combined_report(db_session) -> None:
    await _seed_user(db_session, 1)
    for msg in ("metti la radio jazz", "metti la radio rock", "metti la radio classica"):
        await episodic.record(
            db_session, kind="router.miss", user_id=1, payload={"message": msg},
        )
    from cara.learning import tool_metrics
    for _ in range(4):
        await tool_metrics.record_attempt(
            db_session, parse_ok=False, error_class=ERROR_PARSE_TYPO_PREFIX,
        )
    await db_session.commit()

    embedder = _build_embedder(lambda _t: [1.0, 0.0, 0.0])
    report = await run_weekly(db_session, embedder=embedder, min_cluster_size=3)
    assert len(report.miss_clusters) == 1
    assert len(report.failure_clusters) == 1


async def test_run_weekly_one_pass_failure_does_not_kill_the_other(db_session) -> None:
    """If clustering misses crashes (e.g. embedder borked), the failure
    pass still runs."""
    from cara.learning import tool_metrics
    for _ in range(4):
        await tool_metrics.record_attempt(
            db_session, parse_ok=False, error_class=ERROR_PARSE_TYPO_PREFIX,
        )
    await db_session.commit()

    bad_embedder = MagicMock()
    bad_embedder.encode_many = MagicMock(side_effect=RuntimeError("model dead"))

    # Wrap a real EmbeddingService-shaped object whose encode_many raises.
    class BoomEmbedder:
        dim = 3

        async def encode_many(self, _texts):
            raise RuntimeError("model dead")

        async def encode(self, _t):
            raise RuntimeError("model dead")

    report = await run_weekly(db_session, embedder=BoomEmbedder())
    # Misses pass crashed silently (logged), failures still surfaced.
    assert report.miss_clusters == []
    assert len(report.failure_clusters) == 1
