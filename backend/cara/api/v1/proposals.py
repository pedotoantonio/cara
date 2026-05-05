"""Email proposals endpoints (Phase C of integrations).

  GET    /api/v1/proposals               list pending proposals for the user
  POST   /api/v1/proposals/{id}/accept   accept → create task + audit
  POST   /api/v1/proposals/{id}/reject   reject → mark + learning signal
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.email_proposal import EmailLearningSignal, EmailProposal
from cara.models.user import User
from cara.services import tasks as task_svc
from cara.store import get_session


log = structlog.get_logger(__name__)
router = APIRouter(prefix="/proposals", tags=["proposals"])


def _serialise(p: EmailProposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "message_id": p.message_id,
        "from_address": p.from_address,
        "subject": p.subject,
        "snippet": p.snippet,
        "proposal_type": p.proposal_type,
        "proposal_args": p.proposal_args,
        "confidence": p.confidence,
        "source_layer": p.source_layer,
        "status": p.status,
        "created_at": p.created_at.isoformat(),
        "decided_at": p.decided_at.isoformat() if p.decided_at else None,
    }


@router.get("")
async def list_proposals(
    status_filter: str = "pending",
    limit: int = 50,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(EmailProposal)
            .where(EmailProposal.user_id == user.id)
            .where(EmailProposal.status == status_filter)
            .order_by(EmailProposal.created_at.desc())
            .limit(min(limit, 200))
        )
    ).scalars().all()
    return [_serialise(p) for p in rows]


@router.post("/{proposal_id}/accept")
async def accept_proposal(
    proposal_id: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    p = await session.get(EmailProposal, proposal_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
    if p.status != "pending":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"proposal already {p.status}",
        )

    args = p.proposal_args or {}
    title = (args.get("title") or p.subject or "Promemoria").strip()
    due_iso = args.get("due_date")
    due = None
    if due_iso:
        try:
            due = datetime.fromisoformat(str(due_iso))
        except Exception:  # noqa: BLE001
            due = None

    t = await task_svc.create_task(
        session, user_id=user.id, title=title[:500], due_date=due,
    )

    p.status = "accepted"
    p.decided_at = datetime.now(timezone.utc)
    p.decided_action = {"task_id": str(t.id)}

    # Learning signal: bump accepts for the from_address pattern.
    await _bump_signal(session, user.id, "from", p.from_address or "?", accepts=1)
    await session.commit()
    return {"task_id": str(t.id), "proposal": _serialise(p)}


@router.post("/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    p = await session.get(EmailProposal, proposal_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
    if p.status != "pending":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"proposal already {p.status}",
        )
    p.status = "rejected"
    p.decided_at = datetime.now(timezone.utc)
    await _bump_signal(session, user.id, "from", p.from_address or "?", rejects=1)
    await session.commit()
    return {"proposal": _serialise(p)}


async def _bump_signal(
    session: AsyncSession,
    user_id: int,
    signal_type: str,
    pattern: str,
    *,
    accepts: int = 0,
    rejects: int = 0,
) -> None:
    """Increment accepts or rejects on the (signal_type, pattern) row."""
    if not pattern:
        return
    row = (
        await session.execute(
            select(EmailLearningSignal)
            .where(EmailLearningSignal.user_id == user_id)
            .where(EmailLearningSignal.signal_type == signal_type)
            .where(EmailLearningSignal.pattern == pattern[:255])
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = EmailLearningSignal(
            user_id=user_id,
            signal_type=signal_type,
            pattern=pattern[:255],
            accepts=accepts,
            rejects=rejects,
            last_seen_at=now,
        )
        session.add(row)
    else:
        row.accepts = (row.accepts or 0) + accepts
        row.rejects = (row.rejects or 0) + rejects
        row.last_seen_at = now
