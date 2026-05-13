"""Learn agent — overnight batch jobs that look at CARA's own activity
and surface patterns: habit candidates and router misses.

Both tasks run from Celery beat: nightly habit detection (3:00 AM)
and weekly reflective batch (4:00 AM Sunday). They're cheap to
re-run, idempotent (write upserts via the existing service layer),
and never touch the LLM.
"""

from __future__ import annotations

from typing import Any

import structlog

from sqlalchemy import select, update

from cara.agents._base import _get_sessionmaker, cara_task
from cara.ai.embeddings import EmbeddingService
from cara.learning.habits import detect_and_persist as habits_detect_and_persist
from cara.learning.reflective import run_weekly as reflective_run_weekly
from cara.models.fact import Fact


log = structlog.get_logger(__name__)


@cara_task(agent="learn")
async def detect_habits(idempotency_key: str | None = None) -> dict[str, Any]:
    """Nightly habit-candidate detection on the last 30 days of events."""
    sessionmaker = _get_sessionmaker()
    async with sessionmaker() as session:
        inserted, updated = await habits_detect_and_persist(
            session,
            lookback_days=30,
            min_occurrences=3,
            commit=True,
        )
    log.info("agent.learn.detect_habits.done", inserted=inserted, updated=updated)
    return {"inserted": inserted, "updated": updated}


@cara_task(agent="learn")
async def ingest_recent_facts(
    idempotency_key: str | None = None,
    *,
    batch_size: int = 64,
) -> dict[str, Any]:
    """Backfill embeddings for facts saved with `embedding=NULL`.

    The chat hot path persists facts as soon as a pattern fires (see
    `semantic.extract_facts_async`) but skips the embedding step so it
    doesn't add 200ms of MiniLM cost to every user turn. This job runs
    nightly, picks up everything still-pending, encodes in batches, and
    stamps the vectors back. Once a row has an embedding it's eligible
    for pgvector top-k retrieval at chat time.

    Re-running this task is safe: only NULL rows are selected.
    """
    sessionmaker = _get_sessionmaker()
    embedder = EmbeddingService()
    encoded = 0
    skipped = 0
    async with sessionmaker() as session:
        stmt = (
            select(Fact.id, Fact.text)
            .where(Fact.embedding.is_(None))
            .where(Fact.active.is_(True))
            .order_by(Fact.id)
            .limit(batch_size)
        )
        while True:
            rows = list((await session.execute(stmt)).all())
            if not rows:
                break
            texts = [t for _id, t in rows]
            results = await embedder.encode_many(texts)
            for (fact_id, _), result in zip(rows, results, strict=True):
                if not result.vector:
                    skipped += 1
                    continue
                await session.execute(
                    update(Fact).where(Fact.id == fact_id).values(embedding=result.vector)
                )
                encoded += 1
            await session.commit()
            if len(rows) < batch_size:
                break
    log.info("agent.learn.ingest_recent_facts.done", encoded=encoded, skipped=skipped)
    return {"encoded": encoded, "skipped": skipped}


@cara_task(agent="learn")
async def reflective_run(idempotency_key: str | None = None) -> dict[str, Any]:
    """Weekly reflective batch: cluster router misses + tool failures."""
    sessionmaker = _get_sessionmaker()
    embedder = EmbeddingService()
    async with sessionmaker() as session:
        report = await reflective_run_weekly(session, embedder=embedder)
    log.info(
        "agent.learn.reflective_run.done",
        miss_clusters=len(report.miss_clusters),
        failure_clusters=len(report.failure_clusters),
    )
    return {
        "miss_clusters": len(report.miss_clusters),
        "failure_clusters": len(report.failure_clusters),
    }
