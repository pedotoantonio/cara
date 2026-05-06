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

from cara.agents._base import _get_sessionmaker, cara_task
from cara.ai.embeddings import EmbeddingService
from cara.learning.habits import detect_and_persist as habits_detect_and_persist
from cara.learning.reflective import run_weekly as reflective_run_weekly


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
