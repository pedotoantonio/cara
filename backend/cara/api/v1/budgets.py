"""Budget + Expense endpoints.

  GET    /api/v1/budgets/{year}/{month}              list buckets for the month
  PUT    /api/v1/budgets/{year}/{month}/{category}   upsert target amount
  GET    /api/v1/budgets/{year}/{month}/rollup       category aggregates
                                                     (Wallet `budget_month` widget)

  POST   /api/v1/expenses                            add a single expense
  GET    /api/v1/expenses                            filtered list
  DELETE /api/v1/expenses/{id}                       remove one
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.services import budgets as svc
from cara.store import get_session


router = APIRouter(tags=["budgets"])


# ---------------------------------------------------------------- schemas


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    year: int
    month: int
    category: str
    target_amount_cents: int | None
    note: str | None


class BudgetUpsert(BaseModel):
    target_amount_cents: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    spent_on: date
    amount_cents: int
    category: str
    vendor: str | None
    description: str | None
    extra: dict[str, Any]


class ExpenseCreate(BaseModel):
    spent_on: date
    amount_cents: int = Field(ge=0)
    category: str = Field(default="other", max_length=40)
    vendor: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    extra: dict[str, Any] | None = None


# ---------------------------------------------------------------- budgets


@router.get("/budgets/{year}/{month}", response_model=list[BudgetOut])
async def list_budgets(
    year: int,
    month: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[BudgetOut]:
    if not (1 <= month <= 12):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must be 1..12")
    rows = await svc.list_budgets(session, year=year, month=month)
    return [BudgetOut.model_validate(r) for r in rows]


@router.put("/budgets/{year}/{month}/{category}", response_model=BudgetOut)
async def upsert_budget(
    year: int,
    month: int,
    category: str,
    body: BudgetUpsert,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BudgetOut:
    if not (1 <= month <= 12):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must be 1..12")
    if not (2000 <= year <= 2100):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "year out of range")
    b = await svc.upsert_budget(
        session, year=year, month=month, category=category,
        target_amount_cents=body.target_amount_cents, note=body.note,
        commit=True,
    )
    return BudgetOut.model_validate(b)


@router.get("/budgets/{year}/{month}/rollup")
async def get_month_rollup(
    year: int,
    month: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    if not (1 <= month <= 12):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must be 1..12")
    rollup = await svc.month_rollup(session, year=year, month=month)
    return rollup.to_dict()


# ---------------------------------------------------------------- expenses


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def add_expense(
    body: ExpenseCreate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ExpenseOut:
    e = await svc.add_expense(
        session,
        user_id=user.id,
        spent_on=body.spent_on,
        amount_cents=body.amount_cents,
        category=body.category,
        vendor=body.vendor,
        description=body.description,
        extra=body.extra,
        commit=True,
    )
    return ExpenseOut.model_validate(e)


@router.get("/expenses", response_model=list[ExpenseOut])
async def list_expenses(
    year: int | None = None,
    month: int | None = None,
    category: str | None = None,
    mine: bool = Query(default=False, description="Only my own expenses"),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ExpenseOut]:
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must be 1..12")
    rows = await svc.list_expenses(
        session,
        year=year, month=month, category=category,
        user_id=user.id if mine else None,
        limit=limit,
    )
    return [ExpenseOut.model_validate(r) for r in rows]


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await svc.delete_expense(session, expense_id, commit=True)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "expense not found")
