"""DevicePermission — per-user, per-entity-pattern smart-home authorisation.

Three layers, in priority order from highest to lowest:

  1. **Per-user explicit deny** — wins always (parent locks the alarm
     panel even from themselves).
  2. **Per-user explicit allow** — for one-off exceptions ("teen can
     toggle the cinema scene").
  3. **Role default** — derived from `users.role` via the in-code
     `DEFAULT_ROLE_MATRIX` (see services/smarthome_permissions.py).

Patterns are entity_id globs (canonical: `ha:light.*`, `ha:lock.*`,
`*:alarm_control_panel.*`). Match precedence: longer / more specific
patterns beat shorter / broader ones; ties resolved by latest-updated.

The model rows are tiny — a per-(user, pattern, action) decision. The
service layer in cara/services/smarthome_permissions.py composes them
into a check.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


# Decision slugs (mirrored in the service layer).
PERM_ALLOW = "allow"
PERM_DENY = "deny"
PERM_ASK = "ask"           # require explicit user confirmation in UI


# Action axis: which side-effect is being controlled. Keep small &
# stable; locks/alarm get their own slugs because they almost always
# need a different policy than lights.
ACTION_CONTROL = "control"   # any state-change call_service
ACTION_QUERY = "query"       # read-only state query
ACTION_LOCK = "lock"         # specifically lock/unlock
ACTION_ALARM = "alarm"       # specifically arm/disarm


class DevicePermission(Base):
    """Per-(user, entity_pattern, action) decision row."""

    __tablename__ = "device_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Glob pattern over canonical entity ids: `ha:light.*`, `ha:lock.*`,
    # `*:alarm_control_panel.*`, or a single fully-qualified id.
    entity_pattern: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)

    # Optional human reason for audit/UI display.
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "entity_pattern", "action",
            name="device_permissions_unique_per_user_pattern_action",
        ),
        Index("device_permissions_pattern", "entity_pattern"),
    )
