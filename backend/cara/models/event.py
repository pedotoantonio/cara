"""Event ORM model — episodic memory for CARA.

Every meaningful thing CARA does or sees lands here: chat turns, tool calls,
router decisions, smart-home events, learning signals. The table is the raw
substrate that the semantic / reflective / habit-detection layers later
aggregate over.

Design choices:

- One row per event, append-only. No mutation. Old rows fall off via a
  retention job (default 90 days, configurable).
- `payload` is JSONB so each `kind` can carry its own shape without us
  needing a migration per event family.
- `kind` is a dot-namespaced string (`chat.turn`, `tool.call`,
  `router.miss`, `smarthome.action`). The dots make wildcard prefix
  filtering trivial (`kind LIKE 'tool.%'`).
- `outcome` is a small enum-like string, not an SQL ENUM, because we want
  to add new outcome types without ALTER TYPE rituals.
- `ref_id` is a free-form string FK-by-convention (conversation_id,
  task_id, file_id …). Not a real FK because events can outlive their
  referent — we want the timeline even when the source row is deleted.

NOTE: this model is intentionally NOT yet imported in `cara/models/__init__.py`.
That file is in Antonio's Step 66 working tree; importing here would create a
merge conflict. Once Step 66 lands, add `from cara.models.event import Event`
plus `"Event"` to `__all__`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class Event(Base):
    """Append-only episodic memory row."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        # Most common access pattern: "what did this user do recently?"
        Index("events_user_ts", "user_id", "ts"),
        # Second pattern: "show me all 'tool.call' events" for the diagnostics page.
        Index("events_kind_ts", "kind", "ts"),
        # Third pattern: "all events tied to this conversation".
        Index("events_ref_ts", "ref_id", "ts"),
    )
