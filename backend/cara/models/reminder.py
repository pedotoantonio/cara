"""Reminders (Memorial) ORM models — promemoria umani guidati.

Three tables:

  * `reminder_templates` — admin-seeded catalog of "situations"
    ("Hai una visita prenotata?", "Carta d'identità in scadenza", …).
    The frontend renders these as a guided form: each template carries
    a `fields` JSON describing what to ask the user, and `default_*`
    columns containing the sensible defaults that pre-fill the rest.
  * `reminders` — concrete instance bound to a user, with a due_at and
    optional `recurrence` (yearly/monthly/weekly/custom).
  * `reminder_notifications` — one row per *scheduled* push attempt
    (24h pre / 2h pre / due). The Celery `scan_due` task flips
    `sent_at` when delivery happens; the UNIQUE constraint on
    `(reminder_id, kind, scheduled_at)` prevents double-firing.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


# Category slugs — frozen vocabulary, fixed in MVP.
CATEGORY_FAMILY = "family"
CATEGORY_HEALTH = "health"
CATEGORY_DOCUMENTS = "documents"
CATEGORY_EVENTS = "events"

CATEGORIES = (CATEGORY_FAMILY, CATEGORY_HEALTH, CATEGORY_DOCUMENTS, CATEGORY_EVENTS)

# Status slugs — `active` = live, `done` = completed (terminal for
# one-shot reminders), `snoozed` = active but suppressed until
# `snooze_until`, `archived` = soft-deleted but kept for history.
STATUS_ACTIVE = "active"
STATUS_DONE = "done"
STATUS_SNOOZED = "snoozed"
STATUS_ARCHIVED = "archived"


class ReminderTemplate(Base):
    __tablename__ = "reminder_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title_it: Mapped[str] = mapped_column(String(200), nullable=False)
    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # JSON shape: list of field dicts. Example:
    #   [{"key":"who","label":"Per chi","type":"family_picker","required":true},
    #    {"key":"when","label":"Quando","type":"datetime","required":true},
    #    {"key":"where","label":"Dove","type":"text","required":false}]
    fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Minutes-before-due to fire pre-notices. e.g. [1440, 120] → 24h+2h.
    default_lead_times: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, default=list
    )
    default_recurrence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_in_category: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Optional "soggetto" — il reminder è per un altro membro famiglia.
    family_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    template_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    recurrence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recurrence_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    lead_times: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, default=list
    )
    channels: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=lambda: {"push": True, "telegram": True}
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_ACTIVE, index=True
    )
    snooze_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # `onupdate=func.now()` here forces a server-side compute on UPDATE
    # which puts the column into refresh-required state after flush; the
    # subsequent Pydantic serialisation triggers a lazy-load from inside
    # a sync context and explodes with MissingGreenlet. We set
    # `updated_at` explicitly from the service layer instead.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ReminderNotification(Base):
    __tablename__ = "reminder_notifications"
    __table_args__ = (
        UniqueConstraint(
            "reminder_id", "kind", "scheduled_at",
            name="uq_reminder_notif_kind_time",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    reminder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reminders.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # "due" or "pre_<minutes>" (e.g. "pre_1440" for 24h pre-notice).
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    delivery: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
