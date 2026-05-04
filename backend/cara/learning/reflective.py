"""Reflective batch — cluster router misses + tool-call failures into
admin-reviewable proposals.

Without cloud LLM access, "reflection" is *deterministic clustering*:
group similar failures, find their shared shape, suggest what to fix.

Two input streams:

1. **Router misses** — every Pipeline stage that returned a Miss with
   reason="no_match"-ish, captured in `events` with kind="router.miss".
   We cluster the missed user messages by semantic similarity and
   propose: "this user said similar things 5 times last week and
   nothing handled them — consider adding an intent / skill".

2. **Tool-call failures** — `tool_call_metrics` rows with
   executed=False, grouped by error_class. Each cluster yields a
   diagnostic ("12 calls failed with typo_prefix this week — the
   1.5B is hallucinating TUTOOL again, consider tightening the
   grammar").

Outputs are stored as Proposal rows (separate model below) so the
admin queue persists across restarts. Old proposals decay via
expiry_at when not refreshed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai.embeddings import EmbeddingService
from cara.models.event import Event
from cara.models.tool_metric import ToolCallMetric


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Cluster representation (returned by detect_*; persisted by callers)
# ---------------------------------------------------------------------------


@dataclass
class MissCluster:
    """A group of router-miss messages that look similar to each other."""

    members: list[str]
    centroid_message: str           # representative example (typically the longest)
    user_ids: list[int] = field(default_factory=list)
    suggested_pattern: str | None = None  # heuristic regex from longest common substrings

    @property
    def size(self) -> int:
        return len(self.members)


@dataclass
class FailureCluster:
    """A group of tool-call failures sharing the same error_class."""

    error_class: str
    count: int
    sample_calls: list[str]         # truncated raw_call snippets
    affected_tools: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Router-miss clustering
# ---------------------------------------------------------------------------


_MISS_KIND_PREFIX = "router.miss"


def _cluster_messages(
    messages: list[tuple[str, int | None]],   # (text, user_id)
    embedder: EmbeddingService,
    *,
    similarity_threshold: float = 0.7,
    min_cluster_size: int = 3,
) -> list[MissCluster]:
    """Greedy single-link clustering by cosine similarity.

    For our scale (a handful of misses per day), the O(N²) pairwise
    pass is fine — DBSCAN-grade complexity isn't worth the dependency.
    """
    if not messages:
        return []

    # The clustering happens over the unique texts. We map back to user
    # ids after the clustering pass so the same message said by two
    # users still counts twice in `members` but just once in
    # similarity space.
    unique_texts: list[str] = []
    seen: set[str] = set()
    for text, _ in messages:
        norm = text.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            unique_texts.append(text)

    if len(unique_texts) < min_cluster_size:
        return []

    # Synchronous wrapper around the encoder's async `encode_many`.
    # Callers are expected to provide an embedder backed by a model
    # that's already loaded; the await happens at the orchestration
    # layer in `detect_router_miss_clusters`.
    raise NotImplementedError(
        "_cluster_messages is async-internal; use detect_router_miss_clusters"
    )


async def detect_router_miss_clusters(
    session: AsyncSession,
    *,
    embedder: EmbeddingService,
    since: datetime | None = None,
    min_cluster_size: int = 3,
    similarity_threshold: float = 0.7,
    limit_messages: int = 500,
) -> list[MissCluster]:
    """Pull the recent router-miss events, cluster them, return the clusters
    above `min_cluster_size`.

    Uses the embedder for cosine similarity. Conservative: silent
    return of [] if the embedder hasn't seen any of the messages
    (unembeddable input).
    """
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=7)

    stmt = (
        select(Event)
        .where(Event.ts >= since)
        .where(Event.kind.like(f"{_MISS_KIND_PREFIX}%"))
        .order_by(Event.ts.desc())
        .limit(limit_messages)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return []

    # Each event payload is expected to carry "message". Skip rows
    # without one (older log shape).
    seeds: list[tuple[str, int | None]] = []
    for ev in rows:
        msg = (ev.payload or {}).get("message")
        if isinstance(msg, str) and msg.strip():
            seeds.append((msg, ev.user_id))
    if len(seeds) < min_cluster_size:
        return []

    # De-duplicate by normalised text but keep the (text, user_id) pairs.
    unique_texts: list[str] = []
    seen: set[str] = set()
    for text, _ in seeds:
        norm = text.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            unique_texts.append(text)
    if len(unique_texts) < min_cluster_size:
        return []

    # Encode unique texts.
    encoded = await embedder.encode_many(unique_texts)
    vectors: list[list[float]] = [r.vector for r in encoded]

    # Greedy clustering.
    cluster_ids: list[int] = [-1] * len(unique_texts)
    next_cluster = 0
    for i in range(len(unique_texts)):
        if cluster_ids[i] != -1:
            continue
        cluster_ids[i] = next_cluster
        for j in range(i + 1, len(unique_texts)):
            if cluster_ids[j] != -1:
                continue
            score = _cosine(vectors[i], vectors[j])
            if score >= similarity_threshold:
                cluster_ids[j] = next_cluster
        next_cluster += 1

    # Re-attach all the original (text, user_id) seeds via the
    # normalised text → cluster id map.
    cluster_map: dict[str, int] = {
        unique_texts[i].strip().lower(): cluster_ids[i]
        for i in range(len(unique_texts))
    }
    grouped: dict[int, list[tuple[str, int | None]]] = {}
    for text, uid in seeds:
        cid = cluster_map.get(text.strip().lower())
        if cid is None:
            continue
        grouped.setdefault(cid, []).append((text, uid))

    out: list[MissCluster] = []
    for cid, members in grouped.items():
        if len(members) < min_cluster_size:
            continue
        texts = [m[0] for m in members]
        uids = [m[1] for m in members if m[1] is not None]
        centroid = max(texts, key=len)  # longest sample = best preview
        out.append(MissCluster(
            members=texts,
            centroid_message=centroid,
            user_ids=sorted(set(uids)),
            suggested_pattern=_suggest_pattern(texts),
        ))
    out.sort(key=lambda c: c.size, reverse=True)
    return out


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _suggest_pattern(messages: list[str]) -> str | None:
    """Heuristic regex bozza: longest common token sequence (case-insensitive),
    with non-shared words replaced by `\\S+`.

    This is a *suggestion* shown to the admin — the admin will refine
    it before saving. We don't try to be clever with morphology or
    entity awareness.
    """
    if len(messages) < 2:
        return None
    tokens_per_message: list[list[str]] = [
        re.findall(r"\w+", m.lower()) for m in messages
    ]
    if not all(tokens_per_message):
        return None
    # Tokens common to every message (in any position).
    shared = set(tokens_per_message[0])
    for toks in tokens_per_message[1:]:
        shared &= set(toks)
    if not shared:
        return None
    # Build a regex from the shared tokens (escape, ordered like in the
    # first message for readability).
    ordered_shared = [t for t in tokens_per_message[0] if t in shared]
    if not ordered_shared:
        return None
    return r"\b" + r"\s+\S+\s+".join(re.escape(t) for t in ordered_shared) + r"\b"


# ---------------------------------------------------------------------------
# Tool-call failure clustering
# ---------------------------------------------------------------------------


async def detect_tool_failure_clusters(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    min_cluster_size: int = 3,
) -> list[FailureCluster]:
    """Group tool-call failures by error_class. Returns clusters above
    `min_cluster_size`, sorted count-desc."""
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=7)

    stmt = (
        select(ToolCallMetric)
        .where(ToolCallMetric.ts >= since)
        .where(ToolCallMetric.executed.is_(False))
        .where(ToolCallMetric.error_class.is_not(None))
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return []

    grouped: dict[str, list[ToolCallMetric]] = {}
    for r in rows:
        if r.error_class is None:
            continue
        grouped.setdefault(r.error_class, []).append(r)

    out: list[FailureCluster] = []
    for error_class, metrics in grouped.items():
        if len(metrics) < min_cluster_size:
            continue
        sample_calls = [m.raw_call for m in metrics if m.raw_call][:5]
        affected_tools = sorted({m.tool_name for m in metrics if m.tool_name})
        out.append(FailureCluster(
            error_class=error_class,
            count=len(metrics),
            sample_calls=[c for c in sample_calls if c is not None],
            affected_tools=affected_tools,
        ))
    out.sort(key=lambda c: c.count, reverse=True)
    return out


# ---------------------------------------------------------------------------
# Convenience batch entrypoint
# ---------------------------------------------------------------------------


@dataclass
class ReflectiveReport:
    """End-to-end output the admin dashboard renders."""

    miss_clusters: list[MissCluster] = field(default_factory=list)
    failure_clusters: list[FailureCluster] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


async def run_weekly(
    session: AsyncSession,
    *,
    embedder: EmbeddingService,
    since: datetime | None = None,
    min_cluster_size: int = 3,
) -> ReflectiveReport:
    """Run both passes and return a single ReflectiveReport.

    Designed to be called by a Celery beat task once a week. Errors in
    one pass don't break the other.
    """
    misses: list[MissCluster] = []
    failures: list[FailureCluster] = []

    try:
        misses = await detect_router_miss_clusters(
            session, embedder=embedder, since=since,
            min_cluster_size=min_cluster_size,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("reflective.miss_clusters_failed", error=str(exc))

    try:
        failures = await detect_tool_failure_clusters(
            session, since=since, min_cluster_size=min_cluster_size,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("reflective.failure_clusters_failed", error=str(exc))

    return ReflectiveReport(miss_clusters=misses, failure_clusters=failures)
