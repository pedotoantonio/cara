"""WalletLayout ORM — persisted per-user, per-surface widget layouts.

The Wallet engine (Step 7.1) renders ordered widget cards. This table
stores how each user wants their cards arranged on each surface
(mobile / wall / desktop / watch / tv). Layout changes save here, and
the next time the user opens the surface the order + sizes are
restored.

One row per `(user_id, surface_class)`. The `items` JSONB contains an
ordered list of `{widget_id, size, config}` entries — the engine walks
this list and asks the widget registry to render each.

Preset profiles (Step 7.5) are 4 hardcoded layouts the user can
one-click apply: "Genitore impegnato", "Adolescente", "Bambino sicuro",
"Anziano essenziale". Each is a list of widget_id + size, written into
the user's row by the API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
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


class WalletLayout(Base):
    """Per-(user, surface_class) saved widget order + size + config."""

    __tablename__ = "wallet_layouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # "wall" | "mobile" | "desktop" | "watch" | "tv"
    surface_class: Mapped[str] = mapped_column(String(20), nullable=False)

    # JSONB list of {widget_id: str, size: "small"|"medium"|"large", config: dict}
    # in render order. Frontend drag-drop edits this list and PUTs it back.
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]",
    )

    # The preset slug applied last (or "custom" once the user edits).
    # Useful for the UI to show "you're using the «Genitore» preset".
    preset: Mapped[str | None] = mapped_column(String(40), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "surface_class",
            name="wallet_layouts_unique_per_user_surface",
        ),
    )
