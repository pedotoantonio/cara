"""PresenceEvent — one row per recognised arrival, used for
notification dedupe + history + admin "chi è entrato oggi" widget.

Source: the `presence` agent polls frigate-faces every 30 s and writes
one row per *new* sighting that passes the per-(name, camera) cooldown.
Re-arrivals within the cooldown are not duplicated here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class PresenceEvent(Base):
    __tablename__ = "presence_events"
    __table_args__ = (
        # The frigate-faces sighting id is globally unique across cameras
        # and time, so we use it as the natural dedupe key.
        UniqueConstraint("sighting_id", name="uq_presence_events_sighting"),
        Index("ix_presence_events_seen_at", "seen_at"),
        Index("ix_presence_events_person_seen", "person_name", "seen_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sighting_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    person_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    person_name: Mapped[str] = mapped_column(String(80), nullable=False)
    camera_id: Mapped[str] = mapped_column(String(40), nullable=False)
    is_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    snapshot_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notified_push: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notified_telegram: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    spoken_aloud: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
