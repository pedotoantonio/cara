"""Unit tests for `cara.workflows.auto_confirm`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cara.workflows.auto_confirm import (
    action_signature,
    get_trust,
    list_trust,
    record_confirmed,
    record_rejected,
    revoke_trust,
)
from cara.workflows.base import ProposedAction


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- signature


def test_signature_uses_tool_and_arg_keys() -> None:
    a = ProposedAction(
        tool="add_expense",
        args={"amount_cents": 100, "vendor": "x", "category": "y"},
        summary="x",
    )
    sig = action_signature(a)
    # Keys are sorted; values are NOT in the signature.
    assert sig == "add_expense:amount_cents,category,vendor"


def test_signature_ignores_underscore_keys() -> None:
    a = ProposedAction(
        tool="x", args={"a": 1, "_internal": True, "b": 2}, summary="x",
    )
    assert action_signature(a) == "x:a,b"


def test_signature_stable_across_value_changes() -> None:
    """The signature is structural — same shape, different values → same."""
    a1 = ProposedAction(
        tool="add_expense",
        args={"amount_cents": 100, "category": "groceries", "vendor": "Conad"},
        summary="x",
    )
    a2 = ProposedAction(
        tool="add_expense",
        args={"amount_cents": 9999, "category": "transport", "vendor": "Eni"},
        summary="x",
    )
    assert action_signature(a1) == action_signature(a2)


# ---------------------------------------------------------------- helpers


async def _seed_user(db_session, uid: int):
    from cara.models.user import User

    u = User(
        id=uid, email=f"u{uid}@x.it", password_hash="x",
        full_name=None, is_admin=False, is_active=True, role="parent",
    )
    db_session.add(u)
    await db_session.flush()
    return u


def _action(tool: str = "add_expense", **arg_keys) -> ProposedAction:
    args = {k: 0 for k in arg_keys.keys()} if arg_keys else {
        "amount_cents": 100, "category": "groceries", "vendor": "x",
    }
    return ProposedAction(tool=tool, args=args, summary="x")


# ---------------------------------------------------------------- get_trust before any data


async def test_get_trust_with_no_history_is_not_auto_confirmable(db_session) -> None:
    await _seed_user(db_session, 1)
    decision = await get_trust(
        db_session, user_id=1, workflow_kind="receipt", action=_action(),
    )
    assert decision.auto_confirmable is False
    assert decision.confirms_seen == 0
    assert decision.confirms_remaining == 3


# ---------------------------------------------------------------- streak build


async def test_three_confirms_unlock_auto_confirm(db_session) -> None:
    await _seed_user(db_session, 1)
    a = _action()

    # 3 confirmations → auto_confirmable
    for _ in range(3):
        await record_confirmed(
            db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
        )

    decision = await get_trust(
        db_session, user_id=1, workflow_kind="receipt", action=a,
    )
    assert decision.auto_confirmable is True
    assert decision.confirms_seen == 3


async def test_two_confirms_not_yet_auto_confirmable(db_session) -> None:
    await _seed_user(db_session, 1)
    a = _action()

    for _ in range(2):
        await record_confirmed(
            db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
        )

    decision = await get_trust(
        db_session, user_id=1, workflow_kind="receipt", action=a,
    )
    assert decision.auto_confirmable is False
    assert decision.confirms_remaining == 1


# ---------------------------------------------------------------- streak break


async def test_rejection_resets_streak(db_session) -> None:
    await _seed_user(db_session, 1)
    a = _action()

    for _ in range(3):
        await record_confirmed(
            db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
        )
    await record_rejected(
        db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
    )

    decision = await get_trust(
        db_session, user_id=1, workflow_kind="receipt", action=a,
    )
    assert decision.confirms_seen == 0
    assert decision.auto_confirmable is False


async def test_reject_with_no_history_is_a_noop(db_session) -> None:
    """Rejecting a pattern that's never been confirmed shouldn't crash."""
    await _seed_user(db_session, 1)
    a = _action()
    await record_rejected(
        db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
    )
    # No row was created — get_trust still reports zero history.
    decision = await get_trust(
        db_session, user_id=1, workflow_kind="receipt", action=a,
    )
    assert decision.confirms_seen == 0


# ---------------------------------------------------------------- revoke


async def test_revoke_locks_auto_confirm_off(db_session) -> None:
    await _seed_user(db_session, 1)
    a = _action()
    for _ in range(3):
        await record_confirmed(
            db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
        )
    sig = action_signature(a)
    ok = await revoke_trust(
        db_session, user_id=1, workflow_kind="receipt",
        signature=sig, commit=True,
    )
    assert ok is True

    decision = await get_trust(
        db_session, user_id=1, workflow_kind="receipt", action=a,
    )
    assert decision.auto_confirmable is False
    assert decision.revoked is True


async def test_confirming_after_revoke_clears_revoked(db_session) -> None:
    """Once the user manually re-confirms, the streak restarts at 1
    and `revoked=False`."""
    await _seed_user(db_session, 1)
    a = _action()
    for _ in range(3):
        await record_confirmed(
            db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
        )
    await revoke_trust(
        db_session, user_id=1, workflow_kind="receipt",
        signature=action_signature(a), commit=True,
    )

    # Re-confirm → revoked should clear, streak restarts at 1.
    await record_confirmed(
        db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
    )
    decision = await get_trust(
        db_session, user_id=1, workflow_kind="receipt", action=a,
    )
    assert decision.revoked is False
    assert decision.confirms_seen == 1


async def test_revoke_unknown_signature_returns_false(db_session) -> None:
    await _seed_user(db_session, 1)
    ok = await revoke_trust(
        db_session, user_id=1, workflow_kind="receipt",
        signature="missing:sig", commit=True,
    )
    assert ok is False


# ---------------------------------------------------------------- staleness


async def test_streak_stale_after_90_days(db_session) -> None:
    """A streak that hasn't been touched in > 90 days expires —
    safer to ask again than to silently auto-confirm."""
    await _seed_user(db_session, 1)
    a = _action()
    for _ in range(3):
        await record_confirmed(
            db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
        )

    # Backdate the row so the staleness check kicks in.
    from sqlalchemy import select
    from cara.models.workflow_trust import WorkflowTrust
    row = (await db_session.execute(
        select(WorkflowTrust).where(WorkflowTrust.user_id == 1)
    )).scalar_one()
    row.last_confirmed_at = datetime.now(timezone.utc) - timedelta(days=120)
    await db_session.commit()

    decision = await get_trust(
        db_session, user_id=1, workflow_kind="receipt", action=a,
    )
    assert decision.auto_confirmable is False


# ---------------------------------------------------------------- isolation


async def test_separate_workflow_kinds_keep_separate_streaks(db_session) -> None:
    """A streak built up for `receipt` doesn't apply to `bill`."""
    await _seed_user(db_session, 1)
    a = _action()
    for _ in range(3):
        await record_confirmed(
            db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
        )

    other = await get_trust(
        db_session, user_id=1, workflow_kind="bill", action=a,
    )
    assert other.auto_confirmable is False
    assert other.confirms_seen == 0


async def test_separate_action_signatures_keep_separate_streaks(db_session) -> None:
    """`add_expense` confirmations don't unlock `add_task`."""
    await _seed_user(db_session, 1)
    expense_a = _action(tool="add_expense", amount_cents=0, category=0, vendor=0)
    task_a = _action(tool="add_task", title=0, due_date=0)

    for _ in range(3):
        await record_confirmed(
            db_session, user_id=1, workflow_kind="bill",
            action=expense_a, commit=True,
        )

    decision = await get_trust(
        db_session, user_id=1, workflow_kind="bill", action=task_a,
    )
    assert decision.auto_confirmable is False


# ---------------------------------------------------------------- list_trust


async def test_list_trust_returns_user_rows(db_session) -> None:
    await _seed_user(db_session, 1)
    a = _action()
    await record_confirmed(
        db_session, user_id=1, workflow_kind="receipt", action=a, commit=True,
    )
    rows = await list_trust(db_session, user_id=1)
    assert len(rows) == 1
    assert rows[0].workflow_kind == "receipt"
