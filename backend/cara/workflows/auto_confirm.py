"""Auto-confirm learning — bypass the conferma UI when the user has
confirmed the same shape three times in a row.

The pattern: every workflow proposes side-effect actions, the user
confirms, the workflow runs. After the user has confirmed N times the
same `(workflow_kind, action_signature)`, CARA can skip the prompt and
execute directly. The user can revoke this trust per pattern with one
tap in `/me/workflow-trust`.

This module is the **decision layer** — pure logic over a tracker that
counts streaks. Persistence lives in `cara.models.workflow_trust` (see
below) so the streak survives container restarts.

Action signature is the structural fingerprint of a ProposedAction:
the tool name + the keys present in args (NOT the values, since values
change every receipt). E.g.:

    ProposedAction(tool="add_expense",
                   args={"amount_cents": 8730, "category": "utilities", ...})
    → signature = "add_expense:amount_cents,category,user_id,vendor"

This collapses "any utilities expense" into one trustable shape, which
is what the user actually thinks about when they say "yes always do
this".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.workflow_trust import WorkflowTrust
from cara.workflows.base import ProposedAction


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------


def action_signature(action: ProposedAction) -> str:
    """Stable structural fingerprint of an action.

    Only the tool name and arg KEY set — values vary per request.
    Sorting the keys ensures the signature is order-independent.
    """
    keys = sorted(k for k in action.args.keys() if not k.startswith("_"))
    return f"{action.tool}:{','.join(keys)}"


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


@dataclass
class TrustDecision:
    """Per-action verdict the workflow dispatcher consults."""

    auto_confirmable: bool         # safe to skip the user prompt?
    confirms_seen: int             # current streak of confirmed runs
    threshold: int                 # how many confirms unlock auto-confirm
    revoked: bool = False          # user explicitly turned off auto-confirm

    @property
    def confirms_remaining(self) -> int:
        if self.revoked:
            return self.threshold
        return max(0, self.threshold - self.confirms_seen)


# Default streak length. Configurable via admin_settings later.
_DEFAULT_THRESHOLD = 3

# Streaks expire if untouched for this long — better to ask again than
# to silently auto-confirm something the family hasn't done in 90 days.
_STALE_AFTER = timedelta(days=90)


async def get_trust(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_kind: str,
    action: ProposedAction,
    threshold: int = _DEFAULT_THRESHOLD,
) -> TrustDecision:
    """Should this `(user, workflow_kind, action)` skip the conferma prompt?"""
    sig = action_signature(action)
    row = (await session.execute(
        select(WorkflowTrust).where(
            WorkflowTrust.user_id == user_id,
            WorkflowTrust.workflow_kind == workflow_kind,
            WorkflowTrust.action_signature == sig,
        )
    )).scalar_one_or_none()

    if row is None:
        return TrustDecision(
            auto_confirmable=False, confirms_seen=0, threshold=threshold,
        )
    if row.revoked:
        return TrustDecision(
            auto_confirmable=False,
            confirms_seen=row.confirms_streak,
            threshold=threshold, revoked=True,
        )
    # Streak stale → start over. SQLite (test DB) stores naive datetimes
    # while Postgres (prod) stores tz-aware. Normalise to UTC.
    if row.last_confirmed_at is not None:
        last = row.last_confirmed_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - last
        if age > _STALE_AFTER:
            return TrustDecision(
                auto_confirmable=False, confirms_seen=0, threshold=threshold,
            )
    return TrustDecision(
        auto_confirmable=row.confirms_streak >= threshold,
        confirms_seen=row.confirms_streak,
        threshold=threshold,
    )


# ---------------------------------------------------------------------------
# Update — called after each user-visible confirmation
# ---------------------------------------------------------------------------


async def record_confirmed(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_kind: str,
    action: ProposedAction,
    commit: bool = False,
) -> WorkflowTrust:
    """User said yes (or auto-confirm fired). Bump the streak."""
    sig = action_signature(action)
    row = (await session.execute(
        select(WorkflowTrust).where(
            WorkflowTrust.user_id == user_id,
            WorkflowTrust.workflow_kind == workflow_kind,
            WorkflowTrust.action_signature == sig,
        )
    )).scalar_one_or_none()

    if row is None:
        row = WorkflowTrust(
            user_id=user_id,
            workflow_kind=workflow_kind,
            action_signature=sig,
            confirms_streak=1,
            last_confirmed_at=datetime.now(timezone.utc),
            revoked=False,
        )
        session.add(row)
    else:
        row.confirms_streak = row.confirms_streak + 1 if not row.revoked else 1
        row.revoked = False
        row.last_confirmed_at = datetime.now(timezone.utc)

    await session.flush()
    if commit:
        await session.commit()
    return row


async def record_rejected(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_kind: str,
    action: ProposedAction,
    commit: bool = False,
) -> None:
    """User said no — break the streak. Resets the counter; future
    confirms must build it back up to threshold."""
    sig = action_signature(action)
    row = (await session.execute(
        select(WorkflowTrust).where(
            WorkflowTrust.user_id == user_id,
            WorkflowTrust.workflow_kind == workflow_kind,
            WorkflowTrust.action_signature == sig,
        )
    )).scalar_one_or_none()

    if row is None:
        return
    row.confirms_streak = 0
    row.last_rejected_at = datetime.now(timezone.utc)
    await session.flush()
    if commit:
        await session.commit()


async def revoke_trust(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_kind: str,
    signature: str,
    commit: bool = False,
) -> bool:
    """User explicitly turned off auto-confirm for a pattern.

    Setting `revoked=True` keeps the row (audit) but locks
    `auto_confirmable=False` until the user says yes manually again
    (which clears `revoked` and restarts the streak).
    """
    row = (await session.execute(
        select(WorkflowTrust).where(
            WorkflowTrust.user_id == user_id,
            WorkflowTrust.workflow_kind == workflow_kind,
            WorkflowTrust.action_signature == signature,
        )
    )).scalar_one_or_none()

    if row is None:
        return False
    row.revoked = True
    row.confirms_streak = 0
    await session.flush()
    if commit:
        await session.commit()
    return True


async def list_trust(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[WorkflowTrust]:
    """Everything the user can see in `/me/workflow-trust`."""
    rows = list((await session.execute(
        select(WorkflowTrust).where(WorkflowTrust.user_id == user_id)
        .order_by(WorkflowTrust.last_confirmed_at.desc().nulls_last())
    )).scalars().all())
    return rows
