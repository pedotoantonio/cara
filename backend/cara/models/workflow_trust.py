"""WorkflowTrust ORM — per-user, per-workflow, per-action-signature streak.

Tracks the "auto-confirm" state from Step 3.8: how many consecutive
times a user has confirmed a particular workflow action shape, and
whether they've manually revoked auto-confirm for it.

One row per `(user_id, workflow_kind, action_signature)`. A signature
is something like `add_expense:amount_cents,category,vendor` —
collapses "any utilities expense entry" into one trustable shape.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class WorkflowTrust(Base):
    """User's trust streak for one (workflow, action shape) pair."""

    __tablename__ = "workflow_trust"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Which workflow ("receipt", "bill", "recipe", ...).
    workflow_kind: Mapped[str] = mapped_column(String(40), nullable=False)

    # Action signature: `tool_name:sorted-arg-keys`.
    # Capped at 200 chars — comfortably above what real signatures need.
    action_signature: Mapped[str] = mapped_column(String(200), nullable=False)

    # Streak length. Bumps on confirm, resets to 0 on reject, never
    # decays below 0.
    confirms_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )

    # `True` means the user explicitly turned off auto-confirm for this
    # pattern — the row stays around (audit) but `auto_confirmable`
    # always reads False until the user re-confirms.
    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )

    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "workflow_kind", "action_signature",
            name="workflow_trust_unique_per_user_kind_signature",
        ),
        Index("workflow_trust_user_kind", "user_id", "workflow_kind"),
    )
