"""Budget + Expense service — CRUD + month aggregations.

The ReceiptWorkflow (Step 3.3) writes expenses here when a scontrino is
processed. The Wallet `budget_month` widget reads aggregations.
The admin panel manages target amounts per (year, month, category).

Pure async functions — no global state. Each takes a session.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.budget import (
    CANONICAL_CATEGORIES,
    Budget,
    Expense,
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def is_canonical_category(slug: str) -> bool:
    return slug in CANONICAL_CATEGORIES


def normalise_category(slug: str | None) -> str:
    if not slug or slug.strip().lower() not in CANONICAL_CATEGORIES:
        return "other"
    return slug.strip().lower()


# ---------------------------------------------------------------------------
# Budget CRUD
# ---------------------------------------------------------------------------


async def upsert_budget(
    session: AsyncSession,
    *,
    year: int,
    month: int,
    category: str,
    target_amount_cents: int | None,
    note: str | None = None,
    commit: bool = False,
) -> Budget:
    """Insert or update the (year, month, category) bucket.

    Idempotent — re-calling with the same key updates target/note
    instead of throwing a unique-violation. The auto-generated `extra`
    metadata stays untouched.
    """
    if not (1 <= month <= 12):
        raise ValueError(f"invalid month: {month}")
    category = normalise_category(category)

    existing = (await session.execute(
        select(Budget).where(
            Budget.year == year, Budget.month == month, Budget.category == category,
        )
    )).scalar_one_or_none()

    if existing is None:
        b = Budget(
            year=year, month=month, category=category,
            target_amount_cents=target_amount_cents, note=note,
        )
        session.add(b)
    else:
        b = existing
        b.target_amount_cents = target_amount_cents
        if note is not None:
            b.note = note

    await session.flush()
    if commit:
        await session.commit()
    return b


async def get_budget(
    session: AsyncSession, *, year: int, month: int, category: str,
) -> Budget | None:
    return (await session.execute(
        select(Budget).where(
            Budget.year == year, Budget.month == month,
            Budget.category == normalise_category(category),
        )
    )).scalar_one_or_none()


async def list_budgets(
    session: AsyncSession, *, year: int, month: int,
) -> list[Budget]:
    rows = (await session.execute(
        select(Budget).where(Budget.year == year, Budget.month == month)
        .order_by(Budget.category)
    )).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Expense CRUD
# ---------------------------------------------------------------------------


async def add_expense(
    session: AsyncSession,
    *,
    user_id: int | None,
    spent_on: date,
    amount_cents: int,
    category: str,
    vendor: str | None = None,
    description: str | None = None,
    extra: dict[str, Any] | None = None,
    commit: bool = False,
) -> Expense:
    if amount_cents < 0:
        raise ValueError(f"amount_cents must be ≥ 0 (got {amount_cents})")

    e = Expense(
        user_id=user_id,
        spent_on=spent_on,
        amount_cents=amount_cents,
        category=normalise_category(category),
        vendor=vendor,
        description=description,
        extra=dict(extra or {}),
    )
    session.add(e)
    await session.flush()
    if commit:
        await session.commit()
    return e


async def list_expenses(
    session: AsyncSession,
    *,
    year: int | None = None,
    month: int | None = None,
    category: str | None = None,
    user_id: int | None = None,
    limit: int = 200,
) -> list[Expense]:
    """Filtered listing — newest first."""
    stmt = select(Expense).order_by(Expense.spent_on.desc(), Expense.id.desc())
    conds = []
    if year is not None:
        conds.append(func.extract("year", Expense.spent_on) == year)
    if month is not None:
        conds.append(func.extract("month", Expense.spent_on) == month)
    if category is not None:
        conds.append(Expense.category == normalise_category(category))
    if user_id is not None:
        conds.append(Expense.user_id == user_id)
    if conds:
        stmt = stmt.where(and_(*conds))
    return list((await session.execute(stmt.limit(limit))).scalars().all())


async def delete_expense(
    session: AsyncSession, expense_id: int, *, commit: bool = False,
) -> bool:
    e = (await session.execute(
        select(Expense).where(Expense.id == expense_id)
    )).scalar_one_or_none()
    if e is None:
        return False
    await session.delete(e)
    await session.flush()
    if commit:
        await session.commit()
    return True


# ---------------------------------------------------------------------------
# Month rollup — what the Wallet widget needs
# ---------------------------------------------------------------------------


@dataclass
class CategoryRollup:
    category: str
    spent_cents: int
    target_cents: int | None
    expense_count: int

    @property
    def has_target(self) -> bool:
        return self.target_cents is not None

    @property
    def percentage(self) -> float | None:
        if not self.target_cents:
            return None
        return round(self.spent_cents * 100.0 / self.target_cents, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "spent_cents": self.spent_cents,
            "target_cents": self.target_cents,
            "expense_count": self.expense_count,
            "percentage": self.percentage,
        }


@dataclass
class MonthRollup:
    year: int
    month: int
    total_spent_cents: int
    total_target_cents: int
    categories: list[CategoryRollup]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "month": self.month,
            "total_spent_cents": self.total_spent_cents,
            "total_target_cents": self.total_target_cents,
            "categories": [c.to_dict() for c in self.categories],
        }


async def month_rollup(
    session: AsyncSession, *, year: int, month: int,
) -> MonthRollup:
    """One row per category present in budgets OR expenses for the month.

    Categories with neither budget nor expense are omitted — keeps the
    Wallet widget compact.
    """
    # Budgets in this month.
    budgets_by_cat: dict[str, Budget] = {
        b.category: b for b in await list_budgets(session, year=year, month=month)
    }

    # Expense aggregates per category.
    stmt = (
        select(
            Expense.category,
            func.sum(Expense.amount_cents).label("total"),
            func.count().label("n"),
        )
        .where(
            func.extract("year", Expense.spent_on) == year,
            func.extract("month", Expense.spent_on) == month,
        )
        .group_by(Expense.category)
    )
    expense_rows = list((await session.execute(stmt)).all())
    spent_by_cat = {r[0]: (int(r[1] or 0), int(r[2])) for r in expense_rows}

    all_cats = set(budgets_by_cat.keys()) | set(spent_by_cat.keys())
    categories: list[CategoryRollup] = []
    for cat in sorted(all_cats):
        spent, count = spent_by_cat.get(cat, (0, 0))
        b = budgets_by_cat.get(cat)
        categories.append(CategoryRollup(
            category=cat,
            spent_cents=spent,
            target_cents=b.target_amount_cents if b else None,
            expense_count=count,
        ))

    total_spent = sum(c.spent_cents for c in categories)
    total_target = sum((c.target_cents or 0) for c in categories)

    return MonthRollup(
        year=year, month=month,
        total_spent_cents=total_spent,
        total_target_cents=total_target,
        categories=categories,
    )
