"""Device ORM model — registered surfaces (Wall, mobile, desktop, watch).

A device is one runtime client paired with this CARA family. The Wall
in the living room is one device, Antonio's iPhone is another, Sara's
laptop browser is a third. Each device has its own JWT
("device_token") so it can stream the family WebSocket channel.

Pairing flow (see Step 6.3 of the roadmap):
1. The new device starts and shows a 6-digit pairing code + a QR
   pointing at `/api/v1/devices/pair?code=XYZ123`.
2. An already-authenticated admin opens the link, picks "Wall
   soggiorno" as the friendly name + surface_class, and confirms.
3. Backend mints a long-lived device JWT and persists this row.
4. The device receives the JWT, stores it locally, reconnects.

NOT yet imported in cara/models/__init__.py — see Step 0.3 / 0.4 /
event/tool_metric note. Wired after Antonio's Step 66 commit.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


# Device statuses — small enum-like string column so we can add new
# states (e.g. 'updating', 'maintenance') without an ALTER TYPE.
DEVICE_STATUS_PENDING = "pending"          # paired but never connected
DEVICE_STATUS_ONLINE = "online"
DEVICE_STATUS_OFFLINE = "offline"
DEVICE_STATUS_DISABLED = "disabled"        # admin manually deauthorised
DEVICE_STATUS_ERROR = "error"


# Surface classes — match the frontend `SurfaceProfile.class` enum.
SURFACE_WALL = "wall"
SURFACE_MOBILE = "mobile"
SURFACE_DESKTOP = "desktop"
SURFACE_WATCH = "watch"
SURFACE_TV = "tv"


class Device(Base):
    """A registered CARA client surface (Wall Pi5, mobile, desktop, ...)."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    friendly_name: Mapped[str] = mapped_column(String(80), nullable=False)
    surface_class: Mapped[str] = mapped_column(String(20), nullable=False)

    # Free-form capability dict so we don't need a migration every time
    # a new sensor lands on a Wall (camera, mic, speaker, lipsync, ...).
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Where the device lives, in human terms ("soggiorno", "cucina").
    # NULL on phones/laptops that move around.
    location: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Per-device feature flags / preferences.
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DEVICE_STATUS_PENDING,
        server_default=DEVICE_STATUS_PENDING,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Long-lived JWT issued at pairing. Cleared on deauth so the same
    # row can be re-paired with a new token.
    device_token: Mapped[str | None] = mapped_column(String(800), nullable=True)

    # Audit trail.
    paired_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    paired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("devices_status", "status"),
        Index("devices_surface", "surface_class"),
    )
