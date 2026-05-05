"""Budget + Expense ORM models — family-wide month-by-month spending tracker.

Designed to be the persistence target for the ReceiptWorkflow (Step 3.3):
when a scontrino is processed, an `Expense` row lands here keyed to a
`(family_id, year, month, category)` `Budget` row. The Wallet
`budget_month` widget reads aggregations from this table.

Design choices:

- **Budget = (year, month, category)** — not per-user. Groceries are a
  family thing; the spender's user_id is in `Expense` for audit.
- **Budget.target_amount_cents** is optional. NULL means "track but
  don't compare against a goal". Lets the family use the table for
  observability before they're ready to set a budget.
- **Amounts as integer cents** — cleaner arithmetic than Decimal /
  float. €42.30 = 4230. Display layer converts.
- **Categories are free-form strings**, but the seed list (in the
  service module) is enforced by an UI dropdown so they stay consistent
  for aggregation.

NOT yet imported in cara/models/__init__.py — wired via the new
service in Step 3.5.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
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


# ---------------------------------------------------------------------------
# Canonical category slugs — kept in code so SQL aggregations stay stable.
# ---------------------------------------------------------------------------

CATEGORY_GROCERIES = "groceries"        # supermercato, alimentari
CATEGORY_DINING = "dining"              # ristorante, bar
CATEGORY_TRANSPORT = "transport"         # benzina, mezzi pubblici
CATEGORY_UTILITIES = "utilities"         # bollette
CATEGORY_HEALTH = "health"               # farmacia, visite
CATEGORY_HOME = "home"                   # casa, manutenzione
CATEGORY_LEISURE = "leisure"             # tempo libero, abbonamenti
CATEGORY_KIDS = "kids"                   # spese figli
CATEGORY_OTHER = "other"

CANONICAL_CATEGORIES: tuple[str, ...] = (
    CATEGORY_GROCERIES,
    CATEGORY_DINING,
    CATEGORY_TRANSPORT,
    CATEGORY_UTILITIES,
    CATEGORY_HEALTH,
    CATEGORY_HOME,
    CATEGORY_LEISURE,
    CATEGORY_KIDS,
    CATEGORY_OTHER,
)


# ---------------------------------------------------------------------------
# Budget — one row per (year, month, category)
# ---------------------------------------------------------------------------


class Budget(Base):
    """Monthly target / observability bucket for one spending category."""

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..12
    category: Mapped[str] = mapped_column(String(40), nullable=False)

    # Target amount in cents (€42.30 → 4230). NULL = "no target, just track".
    target_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Optional human-readable note ("solo per la dieta", "viaggio agosto").
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "year", "month", "category",
            name="budgets_unique_per_month_category",
        ),
        Index("budgets_year_month", "year", "month"),
    )


# ---------------------------------------------------------------------------
# Expense — one row per spent amount (typically one per scontrino)
# ---------------------------------------------------------------------------


class Expense(Base):
    """A single recorded expense, optionally tied to a Budget bucket."""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Who entered this expense (NULL allowed only for system-generated entries).
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    spent_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)

    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Free-form metadata: list of items from the receipt, OCR confidence,
    # source ("receipt_workflow" / "manual" / "import"), receipt_file_id.
    extra: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("expenses_date", "spent_on"),
        Index("expenses_category_date", "category", "spent_on"),
        Index("expenses_user_date", "user_id", "spent_on"),
    )
