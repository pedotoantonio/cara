"""PushSubscription ORM — Web Push (VAPID) endpoint per device.

One row per (user, browser/device). Endpoints expire (~30 days for some
push services) — frontend re-subscribes silently on each app load and
PUTs the up-to-date subscription, so this table is meant to churn.

Indexed on (user_id) for the fan-out scheduler that walks tasks and
delivers reminders. Endpoint URL is the natural key — uniqueness on it
prevents the same device registering twice across login sessions.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Public key (browser-generated) for the subscription. Used by
    # pywebpush to encrypt the payload.
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    # Auth secret (browser-generated) — also for payload encryption.
    auth_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_pushed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
