"""Shopping list endpoints — auth, user-scoped."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.schemas.shopping import (
    ShoppingItemCreate,
    ShoppingItemOut,
    ShoppingItemUpdate,
)
from cara.services import shopping as svc
from cara.services.family_bus import publish as fb_publish
from cara.store import get_session

router = APIRouter(prefix="/shopping", tags=["shopping"])


@router.get("", response_model=list[ShoppingItemOut])
async def list_shopping(
    include_bought: bool = True,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ShoppingItemOut]:
    rows = await svc.list_items(session, user_id=user.id, include_bought=include_bought)
    return [ShoppingItemOut.model_validate(r) for r in rows]


@router.post("", response_model=ShoppingItemOut, status_code=status.HTTP_201_CREATED)
async def create_shopping(
    body: ShoppingItemCreate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ShoppingItemOut:
    item = await svc.create_item(session, user_id=user.id, title=body.title, qty=body.qty)
    out = ShoppingItemOut.model_validate(item)
    await fb_publish("shopping.created", user_id=user.id, payload=out.model_dump(mode="json"))
    return out


@router.patch("/{item_id}", response_model=ShoppingItemOut)
async def update_shopping(
    item_id: uuid.UUID,
    body: ShoppingItemUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ShoppingItemOut:
    fields = body.model_fields_set
    kwargs: dict = {}
    if "title" in fields:
        kwargs["title"] = body.title
    if "qty" in fields:
        kwargs["qty"] = body.qty if body.qty is not None else ""
    if "bought" in fields:
        kwargs["bought"] = body.bought
    item = await svc.update_item(session, item_id, user_id=user.id, **kwargs)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    out = ShoppingItemOut.model_validate(item)
    await fb_publish("shopping.updated", user_id=user.id, payload=out.model_dump(mode="json"))
    return out


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shopping(
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await svc.delete_item(session, item_id, user_id=user.id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    await fb_publish("shopping.deleted", user_id=user.id, payload={"id": str(item_id)})


@router.post("/clear-bought")
async def clear_bought(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    n = await svc.clear_bought(session, user_id=user.id)
    return {"removed": n}
