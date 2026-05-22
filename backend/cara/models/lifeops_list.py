"""LifeOps M1 — List, ListItem, PendingApproval models.

Tre tabelle nuove, indipendenti dalle entità lifeops finance (M2) e
routines (M3). Pattern allineato al resto del repo: id Integer PK,
user_id/family scoping, soft delete via deleted_at, no
`onupdate=func.now()` (bug noto async refresh → MissingGreenlet).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class LifeopsList(Base):
    """A user/family list. Replaces ShoppingItem singleton with a
    generic multi-list model (todo, shopping, viaggio, regali, ecc.)."""

    __tablename__ = "lifeops_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # family_id futuro (multi-family). Per single-family stack M1 resta NULL.
    family_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 'user' | 'family' | 'shared'
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="user"
    )
    color_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="lifeops_list_user_slug_uq"),
        Index("lifeops_list_family_idx", "family_id"),
    )


class LifeopsListItem(Base):
    """One row in a list (es. 'pomodori', 'comprare la batteria')."""

    __tablename__ = "lifeops_list_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("lifeops_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Chi ha aggiunto l'item (può essere diverso dal proprietario della lista).
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(280), nullable=False)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    # Quando un child aggiunge item a lista family, parte come pending.
    pending_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LifeopsPendingApproval(Base):
    """Richiesta di un child di modificare una risorsa shared. Notifica
    al supervisor (parent o user con is_supervisor=true). Scadenza 48h."""

    __tablename__ = "lifeops_pending_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requested_by_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supervisor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    # 'list_item' | 'transaction' | ...
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    target_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    # 'pending' | 'approved' | 'rejected' | 'expired'
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("lifeops_pending_state_idx", "state", "expires_at"),
    )
