"""Shopping list persistence helpers — scoped per user."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models import ShoppingItem


async def list_items(
    session: AsyncSession, *, user_id: int, include_bought: bool = True
) -> list[ShoppingItem]:
    stmt = select(ShoppingItem).where(ShoppingItem.user_id == user_id)
    if not include_bought:
        stmt = stmt.where(ShoppingItem.bought.is_(False))
    stmt = stmt.order_by(ShoppingItem.bought.asc(), ShoppingItem.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def create_item(
    session: AsyncSession, *, user_id: int, title: str, qty: str | None = None
) -> ShoppingItem:
    item = ShoppingItem(user_id=user_id, title=title, qty=qty)
    session.add(item)
    await session.flush()
    return item


async def get_item(
    session: AsyncSession, item_id: uuid.UUID, *, user_id: int
) -> ShoppingItem | None:
    stmt = select(ShoppingItem).where(
        ShoppingItem.id == item_id, ShoppingItem.user_id == user_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_item(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    user_id: int,
    title: str | None = None,
    qty: str | None | object = None,
    bought: bool | None = None,
) -> ShoppingItem | None:
    item = await get_item(session, item_id, user_id=user_id)
    if item is None:
        return None
    if title is not None:
        item.title = title
    if qty is not None and qty is not False:
        item.qty = qty if qty != "" else None  # type: ignore[assignment]
    if bought is not None and bought != item.bought:
        item.bought = bought
        item.bought_at = datetime.now(UTC) if bought else None
    await session.flush()
    return item


async def delete_item(
    session: AsyncSession, item_id: uuid.UUID, *, user_id: int
) -> bool:
    item = await get_item(session, item_id, user_id=user_id)
    if item is None:
        return False
    await session.delete(item)
    return True


async def clear_bought(session: AsyncSession, *, user_id: int) -> int:
    """Delete every item already bought by this user. Returns count removed."""
    items = await list_items(session, user_id=user_id, include_bought=True)
    bought = [i for i in items if i.bought]
    for i in bought:
        await session.delete(i)
    return len(bought)
