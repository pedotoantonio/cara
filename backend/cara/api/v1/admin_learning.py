"""Admin endpoints for the learning layer — habits, reflective batch, tool-call telemetry.

These wire the modules built in Steps 0.4 / 8.4 / 8.5 to an HTTP surface
the admin UI consumes. All routes require `is_admin=True`.

  POST   /api/v1/admin/habits/detect             run the deterministic detector
  GET    /api/v1/admin/habits/candidates         list pending candidates
  POST   /api/v1/admin/habits/{id}/review        accept / reject / dismiss

  POST   /api/v1/admin/reflective/run            run the weekly batch right now
                                                 (returns {miss_clusters, failure_clusters})

  GET    /api/v1/admin/tool-metrics/stats        success funnel for the window
  GET    /api/v1/admin/tool-metrics/top-failures top error_class counts
  GET    /api/v1/admin/tool-metrics/recent       newest failed attempts

Reflective `run` requires the embedding model — heavy on first call.
We make that explicit to the admin (clear status field).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai.embeddings import EmbeddingService
from cara.api.deps import require_admin
from cara.learning import habits, reflective, tool_metrics
from cara.learning.tool_metrics import (
    ERROR_EXEC_EXCEPTION,
    ERROR_MISSING_ARG,
    ERROR_PARSE_MALFORMED,
    ERROR_PARSE_TYPO_PREFIX,
    ERROR_PERMISSION_DENIED,
    ERROR_SCHEMA_INVALID,
    ERROR_UNKNOWN_TOOL,
)
from cara.models.user import User
from cara.store import get_session


router = APIRouter(prefix="/admin", tags=["admin-learning"])


# ============================================================================
# habits
# ============================================================================


class HabitCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    kind: str
    weekday: int
    hour_bucket: int
    pattern: dict[str, Any]
    occurrences: int
    confidence: float
    first_seen: datetime
    last_seen: datetime
    status: str


class HabitDetectRequest(BaseModel):
    lookback_days: int = Field(default=30, ge=1, le=365)
    min_occurrences: int = Field(default=3, ge=2, le=50)


class HabitDetectResponse(BaseModel):
    inserted: int
    updated: int
    lookback_days: int


class HabitReviewRequest(BaseModel):
    decision: Literal["accept", "reject", "dismiss"]


@router.post("/habits/detect", response_model=HabitDetectResponse)
async def run_habit_detection(
    body: HabitDetectRequest,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HabitDetectResponse:
    """Run the deterministic detector on the recent event log."""
    inserted, updated = await habits.detect_and_persist(
        session,
        lookback_days=body.lookback_days,
        min_occurrences=body.min_occurrences,
        commit=True,
    )
    return HabitDetectResponse(
        inserted=inserted, updated=updated, lookback_days=body.lookback_days,
    )


@router.get("/habits/candidates", response_model=list[HabitCandidateOut])
async def list_habit_candidates(
    user_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[HabitCandidateOut]:
    rows = await habits.list_pending(session, user_id=user_id, limit=limit)
    return [HabitCandidateOut.model_validate(r) for r in rows]


@router.post("/habits/{candidate_id}/review")
async def review_habit_candidate(
    candidate_id: int,
    body: HabitReviewRequest,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    ok = await habits.review_candidate(
        session,
        candidate_id,
        reviewer_user_id=admin.id,
        decision=body.decision,
        commit=True,
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")
    return {"id": candidate_id, "decision": body.decision}


# ============================================================================
# reflective batch
# ============================================================================


class ReflectiveRunRequest(BaseModel):
    since_days: int = Field(default=7, ge=1, le=180)
    min_cluster_size: int = Field(default=3, ge=2, le=20)


@router.post("/reflective/run")
async def run_reflective_batch(
    body: ReflectiveRunRequest,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Run both clustering passes (router-misses + tool-failures) and
    return a structured report.

    The router-miss pass calls the embedding model on every distinct
    miss in the window — heavy on first call (~3s cold). Failure
    clustering is pure SQL, fast.
    """
    # Lazy embedder: shared singleton would also work; this avoids
    # binding to anything global before we're sure cloud isn't enabled.
    embedder = EmbeddingService()

    since = datetime.now(timezone.utc) - timedelta(days=body.since_days)
    report = await reflective.run_weekly(
        session,
        embedder=embedder,
        since=since,
        min_cluster_size=body.min_cluster_size,
    )

    return {
        "generated_at": report.generated_at.isoformat(),
        "since": since.isoformat(),
        "miss_clusters": [
            {
                "size": c.size,
                "centroid_message": c.centroid_message,
                "user_ids": c.user_ids,
                "suggested_pattern": c.suggested_pattern,
                "samples": c.members[:5],
            }
            for c in report.miss_clusters
        ],
        "failure_clusters": [
            {
                "error_class": c.error_class,
                "count": c.count,
                "affected_tools": c.affected_tools,
                "sample_calls": c.sample_calls,
            }
            for c in report.failure_clusters
        ],
    }


# ============================================================================
# tool-call metrics
# ============================================================================


@router.get("/tool-metrics/stats")
async def tool_metrics_stats(
    since_days: int = Query(default=7, ge=1, le=180),
    tool_name: str | None = None,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    s = await tool_metrics.stats(session, since=since, tool_name=tool_name)
    return {
        "since_days": since_days,
        "tool_name": tool_name,
        "total": s.total,
        "parse_ok": s.parse_ok,
        "name_match": s.name_match,
        "args_valid": s.args_valid,
        "executed": s.executed,
        "parse_rate": round(s.parse_rate, 3),
        "success_rate": round(s.success_rate, 3),
    }


@router.get("/tool-metrics/top-failures")
async def tool_metrics_top_failures(
    since_days: int = Query(default=7, ge=1, le=180),
    limit: int = Query(default=10, ge=1, le=50),
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    rows = await tool_metrics.top_failure_classes(session, since=since, limit=limit)
    return {
        "since_days": since_days,
        "items": [{"error_class": cls, "count": cnt} for cls, cnt in rows],
        "vocabulary": [
            ERROR_PARSE_TYPO_PREFIX, ERROR_PARSE_MALFORMED, ERROR_UNKNOWN_TOOL,
            ERROR_MISSING_ARG, ERROR_SCHEMA_INVALID, ERROR_PERMISSION_DENIED,
            ERROR_EXEC_EXCEPTION,
        ],
    }


@router.get("/tool-metrics/recent")
async def tool_metrics_recent(
    limit: int = Query(default=20, ge=1, le=200),
    error_class: str | None = None,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    classes = [error_class] if error_class else None
    rows = await tool_metrics.recent_failures(
        session, limit=limit, error_classes=classes,
    )
    return {
        "items": [
            {
                "id": r.id,
                "ts": r.ts.isoformat() if r.ts else None,
                "user_id": r.user_id,
                "tool_name": r.tool_name,
                "error_class": r.error_class,
                "raw_call": r.raw_call,
                "parse_ok": r.parse_ok,
                "name_match": r.name_match,
                "args_valid": r.args_valid,
                "conversation_id": r.conversation_id,
            }
            for r in rows
        ],
    }
