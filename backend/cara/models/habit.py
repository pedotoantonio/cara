"""HabitCandidate ORM — patterns the detector noticed and admin reviews.

A candidate is a hypothesis: "every Tuesday around 18:00, this user
creates a `task` with the title pattern X". The detector emits one row
per (user_id, kind, weekday, hour_bucket) bucket whose occurrence count
crosses the threshold (default 3 in 30 days).

Status flow: pending → accepted | rejected. Accepted candidates are
the seeds of proactivity rules (Step 8.6/8.7) and skill suggestions
(Step 8.X). Rejected candidates are remembered too so the detector
doesn't keep re-proposing the same idea.

NOT yet imported in cara/models/__init__.py — same wiring deferral as
Event/Fact/Device/ToolCallMetric.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


HABIT_STATUS_PENDING = "pending"
HABIT_STATUS_ACCEPTED = "accepted"
HABIT_STATUS_REJECTED = "rejected"
HABIT_STATUS_DISMISSED = "dismissed"   # admin: "yes I see, but ignore"


class HabitCandidate(Base):
    """One detected habit hypothesis awaiting admin review."""

    __tablename__ = "habit_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # The event kind whose recurrence we're describing — e.g. "task.created",
    # "shopping.add", "radio.start". Kept as a free-form string so we can
    # add new event families without a migration.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)

    # Time pattern. weekday ∈ 0..6 (Monday=0). hour_bucket ∈ 0..7
    # (3-hour buckets: 0=00-03, 1=03-06, …, 7=21-24).
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    hour_bucket: Mapped[int] = mapped_column(Integer, nullable=False)

    # Free-form pattern data the detector built (typical title, common
    # tool args, etc.). Frontend renders this as the "what we noticed".
    pattern: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=HABIT_STATUS_PENDING,
        server_default=HABIT_STATUS_PENDING,
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "kind", "weekday", "hour_bucket",
            name="habit_candidates_unique_per_user_kind_slot",
        ),
        Index("habit_candidates_status", "status"),
    )
