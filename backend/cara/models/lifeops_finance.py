"""LifeOps M2 — Finance models (Account, FinanceCategory, Transaction).

Storage amount: Numeric(12, 2) in DB, Decimal in Python, mai float.
balance_cents su Account è cached, ricalcolato su mutation.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class LifeopsAccount(Base):
    """Conto/portafoglio per-utente. Mai shared cross-user (privacy)."""

    __tablename__ = "lifeops_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # 'cash' | 'bank' | 'card' | 'savings' | 'other'
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="EUR"
    )
    # Cached balance (cents) — ricomputato da Celery task / endpoint
    balance_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
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


class LifeopsFinanceCategory(Base):
    """Categoria expense/income per-famiglia. Seedate 12 in M1 (single-family)."""

    __tablename__ = "lifeops_finance_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Single-family stack: family_id NULL = "categorie globali della casa"
    family_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(48), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    # 'expense' | 'income'
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    color_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    __table_args__ = (
        UniqueConstraint("family_id", "slug", name="lifeops_fincat_family_slug_uq"),
    )


class LifeopsTransaction(Base):
    """Spesa o entrata. Sempre per-user, sempre Numeric(12,2).

    state:
    - 'pending'   = creata da NLU, attende conferma utente
    - 'confirmed' = registrata, contribuisce al balance
    - 'rejected'  = annullata, niente effetto sul balance
    """

    __tablename__ = "lifeops_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("lifeops_accounts.id"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("lifeops_finance_categories.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # 'expense' | 'income' | 'transfer'
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    happened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(String(280), nullable=True)
    # Frase originale dell'utente (audit / debug NLU). PRIVATE: mai loggata.
    raw_utterance: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'pending' | 'confirmed' | 'rejected'
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="confirmed"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
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
        Index("lifeops_tx_user_when_idx", "user_id", "happened_at"),
        Index("lifeops_tx_state_idx", "state"),
    )
