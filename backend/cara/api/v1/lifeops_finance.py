"""LifeOps M2 — Finance REST API.

Endpoint:
    GET    /api/v1/lifeops/finance/accounts
    POST   /api/v1/lifeops/finance/accounts
    PATCH  /api/v1/lifeops/finance/accounts/{id}

    GET    /api/v1/lifeops/finance/categories

    GET    /api/v1/lifeops/finance/transactions
    POST   /api/v1/lifeops/finance/transactions
    POST   /api/v1/lifeops/finance/transactions/{id}/confirm
    POST   /api/v1/lifeops/finance/transactions/{id}/reject
    PATCH  /api/v1/lifeops/finance/transactions/{id}
    DELETE /api/v1/lifeops/finance/transactions/{id}

    GET    /api/v1/lifeops/finance/summary
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models import (
    LifeopsAccount,
    LifeopsFinanceCategory,
    LifeopsTransaction,
    User,
)
from cara.services import audit as audit_svc
from cara.store import get_session


log = structlog.get_logger(__name__)
router = APIRouter(prefix="/lifeops/finance", tags=["lifeops-finance"])


# ─── Schemas ─────────────────────────────────────────────────────────


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    kind: str
    currency: str
    balance_cents: int
    archived_at: datetime | None
    created_at: datetime


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    kind: Literal["cash", "bank", "card", "savings", "other"] = "cash"
    currency: str = Field("EUR", min_length=3, max_length=3)


class AccountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    archived: bool | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    family_id: int | None
    slug: str
    label: str
    direction: str
    icon: str | None
    color_token: str | None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    account_id: int
    category_id: int | None
    amount: Decimal
    direction: str
    happened_at: datetime
    description: str | None
    state: str
    confirmed_at: datetime | None
    created_at: datetime

    @field_serializer("amount")
    def _amt(self, value: Decimal) -> str:
        return str(value)


class TransactionCreate(BaseModel):
    amount: Decimal = Field(..., ge=Decimal("0.01"), max_digits=12, decimal_places=2)
    direction: Literal["expense", "income", "transfer"] = "expense"
    account_id: int | None = None  # None → primo cash account dell'utente
    category_slug: str | None = None
    happened_at: datetime | None = None
    description: str | None = Field(None, max_length=280)
    raw_utterance: str | None = None
    state: Literal["pending", "confirmed"] = "confirmed"

    @field_serializer("amount")
    def _amt(self, value: Decimal) -> str:
        return str(value)


class TransactionUpdate(BaseModel):
    amount: Decimal | None = None
    direction: Literal["expense", "income", "transfer"] | None = None
    category_slug: str | None = None
    happened_at: datetime | None = None
    description: str | None = None


# ─── Helpers ─────────────────────────────────────────────────────────


async def _default_account(session: AsyncSession, user: User) -> LifeopsAccount:
    stmt = (
        select(LifeopsAccount)
        .where(
            LifeopsAccount.user_id == user.id,
            LifeopsAccount.deleted_at.is_(None),
            LifeopsAccount.archived_at.is_(None),
        )
        .order_by(LifeopsAccount.created_at.asc())
        .limit(1)
    )
    acc = (await session.execute(stmt)).scalar_one_or_none()
    if acc is None:
        # Crea Contanti default
        acc = LifeopsAccount(
            user_id=user.id, name="Contanti", kind="cash", currency="EUR"
        )
        session.add(acc)
        await session.flush()
    return acc


async def _category_by_slug(
    session: AsyncSession, slug: str | None
) -> LifeopsFinanceCategory | None:
    if not slug:
        return None
    stmt = select(LifeopsFinanceCategory).where(
        LifeopsFinanceCategory.slug == slug,
        LifeopsFinanceCategory.family_id.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _recompute_balance(
    session: AsyncSession, account_id: int
) -> int:
    """Ricalcola balance_cents da tutte le transactions confirmed.
    Income → +, expense → -, transfer ignorato per ora.
    """
    stmt = select(LifeopsTransaction).where(
        LifeopsTransaction.account_id == account_id,
        LifeopsTransaction.state == "confirmed",
        LifeopsTransaction.deleted_at.is_(None),
    )
    rows = (await session.execute(stmt)).scalars().all()
    total = Decimal("0")
    for tx in rows:
        if tx.direction == "income":
            total += tx.amount
        elif tx.direction == "expense":
            total -= tx.amount
    cents = int(total * 100)
    acc = await session.get(LifeopsAccount, account_id)
    if acc:
        acc.balance_cents = cents
        acc.updated_at = datetime.now(timezone.utc)
        await session.flush()
    return cents


# ─── Accounts ────────────────────────────────────────────────────────


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    archived: bool = False,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[AccountOut]:
    stmt = select(LifeopsAccount).where(
        LifeopsAccount.user_id == user.id,
        LifeopsAccount.deleted_at.is_(None),
    )
    if not archived:
        stmt = stmt.where(LifeopsAccount.archived_at.is_(None))
    stmt = stmt.order_by(LifeopsAccount.created_at.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return [AccountOut.model_validate(r) for r in rows]


@router.post("/accounts", response_model=AccountOut, status_code=201)
async def create_account(
    body: AccountCreate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AccountOut:
    acc = LifeopsAccount(
        user_id=user.id,
        name=body.name,
        kind=body.kind,
        currency=body.currency.upper(),
    )
    session.add(acc)
    await session.flush()
    return AccountOut.model_validate(acc)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: int,
    body: AccountUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AccountOut:
    acc = await session.get(LifeopsAccount, account_id)
    if acc is None or acc.deleted_at is not None or acc.user_id != user.id:
        raise HTTPException(404, "account not found")
    if body.name is not None:
        acc.name = body.name
    if body.archived is not None:
        acc.archived_at = datetime.now(timezone.utc) if body.archived else None
    acc.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return AccountOut.model_validate(acc)


# ─── Categories ──────────────────────────────────────────────────────


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    direction: Literal["expense", "income", "all"] = "all",
    session: AsyncSession = Depends(get_session),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> list[CategoryOut]:
    stmt = select(LifeopsFinanceCategory)
    if direction != "all":
        stmt = stmt.where(LifeopsFinanceCategory.direction == direction)
    stmt = stmt.order_by(LifeopsFinanceCategory.id.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return [CategoryOut.model_validate(r) for r in rows]


# ─── Transactions ────────────────────────────────────────────────────


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(
    state: Literal["pending", "confirmed", "rejected", "all"] = "all",
    direction: Literal["expense", "income", "transfer", "all"] = "all",
    account_id: int | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[TransactionOut]:
    if limit < 1 or limit > 500:
        limit = 100
    stmt = select(LifeopsTransaction).where(
        LifeopsTransaction.user_id == user.id,
        LifeopsTransaction.deleted_at.is_(None),
    )
    if state != "all":
        stmt = stmt.where(LifeopsTransaction.state == state)
    if direction != "all":
        stmt = stmt.where(LifeopsTransaction.direction == direction)
    if account_id is not None:
        stmt = stmt.where(LifeopsTransaction.account_id == account_id)
    stmt = stmt.order_by(LifeopsTransaction.happened_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [TransactionOut.model_validate(r) for r in rows]


@router.post("/transactions", response_model=TransactionOut, status_code=201)
async def create_transaction(
    body: TransactionCreate,
    request: Request,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TransactionOut:
    account_id = body.account_id
    if account_id is None:
        acc = await _default_account(session, user)
        account_id = acc.id
    else:
        # verifica ownership
        acc = await session.get(LifeopsAccount, account_id)
        if acc is None or acc.user_id != user.id:
            raise HTTPException(404, "account not found")

    cat = await _category_by_slug(session, body.category_slug)

    tx = LifeopsTransaction(
        user_id=user.id,
        account_id=account_id,
        category_id=cat.id if cat else None,
        amount=body.amount,
        direction=body.direction,
        happened_at=body.happened_at or datetime.now(timezone.utc),
        description=body.description,
        raw_utterance=body.raw_utterance,
        state=body.state,
        confirmed_at=datetime.now(timezone.utc) if body.state == "confirmed" else None,
    )
    session.add(tx)
    await session.flush()

    if body.state == "confirmed":
        await _recompute_balance(session, account_id)

    await audit_svc.record(
        session,
        actor=user,
        action="lifeops.tx.create",
        target_kind="lifeops_transaction",
        target_id=str(tx.id),
        detail={
            "amount_eur": str(body.amount),
            "direction": body.direction,
            "state": body.state,
        },
        ip=request.client.host if request.client else None,
    )

    return TransactionOut.model_validate(tx)


@router.post("/transactions/{tx_id}/confirm", response_model=TransactionOut)
async def confirm_transaction(
    tx_id: int,
    request: Request,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TransactionOut:
    tx = await session.get(LifeopsTransaction, tx_id)
    if tx is None or tx.user_id != user.id or tx.deleted_at is not None:
        raise HTTPException(404, "transaction not found")
    if tx.state == "confirmed":
        return TransactionOut.model_validate(tx)
    if tx.state == "rejected":
        raise HTTPException(409, "transaction already rejected")

    tx.state = "confirmed"
    tx.confirmed_at = datetime.now(timezone.utc)
    tx.updated_at = tx.confirmed_at
    await session.flush()
    await _recompute_balance(session, tx.account_id)
    await audit_svc.record(
        session,
        actor=user,
        action="lifeops.tx.confirm",
        target_kind="lifeops_transaction",
        target_id=str(tx.id),
        ip=request.client.host if request.client else None,
    )
    return TransactionOut.model_validate(tx)


@router.post("/transactions/{tx_id}/reject", response_model=TransactionOut)
async def reject_transaction(
    tx_id: int,
    request: Request,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TransactionOut:
    tx = await session.get(LifeopsTransaction, tx_id)
    if tx is None or tx.user_id != user.id or tx.deleted_at is not None:
        raise HTTPException(404, "transaction not found")
    if tx.state == "confirmed":
        # Già confermata → cancellala come "rejected" (soft) + ricomputa
        was_confirmed = True
    else:
        was_confirmed = False
    tx.state = "rejected"
    tx.updated_at = datetime.now(timezone.utc)
    await session.flush()
    if was_confirmed:
        await _recompute_balance(session, tx.account_id)
    return TransactionOut.model_validate(tx)


@router.delete("/transactions/{tx_id}", status_code=204)
async def delete_transaction(
    tx_id: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    tx = await session.get(LifeopsTransaction, tx_id)
    if tx is None or tx.user_id != user.id or tx.deleted_at is not None:
        raise HTTPException(404, "transaction not found")
    was_confirmed = tx.state == "confirmed"
    tx.deleted_at = datetime.now(timezone.utc)
    tx.updated_at = tx.deleted_at
    await session.flush()
    if was_confirmed:
        await _recompute_balance(session, tx.account_id)


# ─── Summary ─────────────────────────────────────────────────────────


class SummaryOut(BaseModel):
    total_expense: str
    total_income: str
    net: str
    count_expense: int
    count_income: int
    by_category: list[dict[str, Any]]


@router.get("/summary", response_model=SummaryOut)
async def summary(
    from_iso: str | None = None,
    to_iso: str | None = None,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SummaryOut:
    stmt = select(LifeopsTransaction).where(
        LifeopsTransaction.user_id == user.id,
        LifeopsTransaction.state == "confirmed",
        LifeopsTransaction.deleted_at.is_(None),
    )
    if from_iso:
        stmt = stmt.where(
            LifeopsTransaction.happened_at >= datetime.fromisoformat(from_iso)
        )
    if to_iso:
        stmt = stmt.where(
            LifeopsTransaction.happened_at <= datetime.fromisoformat(to_iso)
        )
    rows = (await session.execute(stmt)).scalars().all()

    total_exp = Decimal("0")
    total_inc = Decimal("0")
    count_exp = 0
    count_inc = 0
    by_cat: dict[int | None, dict[str, Any]] = {}

    for tx in rows:
        if tx.direction == "expense":
            total_exp += tx.amount
            count_exp += 1
        elif tx.direction == "income":
            total_inc += tx.amount
            count_inc += 1
        bucket = by_cat.setdefault(
            tx.category_id,
            {"category_id": tx.category_id, "amount": Decimal("0"), "count": 0},
        )
        bucket["amount"] += tx.amount if tx.direction == "income" else -tx.amount
        bucket["count"] += 1

    by_category = [
        {**v, "amount": str(v["amount"])} for v in by_cat.values()
    ]

    return SummaryOut(
        total_expense=str(total_exp),
        total_income=str(total_inc),
        net=str(total_inc - total_exp),
        count_expense=count_exp,
        count_income=count_inc,
        by_category=by_category,
    )
