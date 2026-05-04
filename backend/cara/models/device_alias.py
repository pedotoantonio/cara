"""DeviceAlias ORM — admin-curated alias overrides for smart-home entities.

The smart-home NLU resolver (Step 5.5) walks four match stages: exact
alias → substring → embedding → presence-disambiguation. The "alias"
list it consults comes from two sources:

  1. Auto-derived from each `Entity.friendly_name` returned by the
     adapter (e.g. HA's `friendly_name="Luce cucina"`).
  2. Admin overrides stored in this table — the household-specific
     phrases CARA must understand: *"il lampadario", "la luce sopra
     il tavolo", "la lampada di Sara"*.

The auto layer is regenerated on every entity discovery; this table
persists across restarts and survives HA reboots even if a friendly
name changes.

`source_user_id` is the admin who added the alias (audit). Aliases
without `entity_id` are reserved for future "rule-based" expansions
(e.g. *"luce* → multi-target") and currently rejected by the service.
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


class DeviceAlias(Base):
    """Admin-curated phrase → entity_id mapping for smart-home NLU."""

    __tablename__ = "device_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Canonical entity id from the adapter, e.g. "ha:light.cucina".
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)

    # The phrase the user actually says ("il lampadario", "la luce sopra
    # il tavolo"). Stored case-insensitive — duplicates differing only by
    # case are forbidden by the unique constraint after lowercasing.
    alias: Mapped[str] = mapped_column(String(120), nullable=False)

    # Optional area scope ("cucina", "soggiorno"). When present, the NLU
    # presence-disambiguation step uses it to break ties.
    area: Mapped[str | None] = mapped_column(String(80), nullable=True)

    source_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "entity_id", "alias",
            name="device_aliases_unique_per_entity_alias",
        ),
        Index("device_aliases_entity", "entity_id"),
    )
