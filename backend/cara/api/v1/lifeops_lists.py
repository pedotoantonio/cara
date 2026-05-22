"""LifeOps M1 — REST API for lists + pending approvals.

Endpoint:
    GET    /api/v1/lifeops/lists
    POST   /api/v1/lifeops/lists
    GET    /api/v1/lifeops/lists/{id}
    PATCH  /api/v1/lifeops/lists/{id}
    DELETE /api/v1/lifeops/lists/{id}
    POST   /api/v1/lifeops/lists/{id}/items
    PATCH  /api/v1/lifeops/lists/{id}/items/{item_id}
    DELETE /api/v1/lifeops/lists/{id}/items/{item_id}

    GET    /api/v1/lifeops/pending
    POST   /api/v1/lifeops/pending/{id}/approve
    POST   /api/v1/lifeops/pending/{id}/reject

Pattern allineato al resto del repo: auth via `get_current_user`,
audit log su mutazioni, family-bus publish su events `lifeops.*`,
soft delete via `deleted_at`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models import (
    LifeopsList,
    LifeopsListItem,
    LifeopsPendingApproval,
    User,
)
from cara.services import audit as audit_svc
from cara.store import get_session


log = structlog.get_logger(__name__)
router = APIRouter(prefix="/lifeops", tags=["lifeops"])


# ─── Schemas ─────────────────────────────────────────────────────────


class ListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    family_id: int | None
    slug: str
    title: str
    icon: str | None
    scope: Literal["user", "family", "shared"]
    color_token: str | None
    sort_order: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ListCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=48)
    title: str = Field(..., min_length=1, max_length=120)
    icon: str | None = Field(None, max_length=32)
    scope: Literal["user", "family", "shared"] = "user"
    color_token: str | None = Field(None, max_length=32)


class ListUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    icon: str | None = Field(None, max_length=32)
    color_token: str | None = Field(None, max_length=32)
    sort_order: int | None = None
    archived: bool | None = None


class ListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    list_id: int
    user_id: int
    title: str
    qty: float | None
    unit: str | None
    notes: str | None
    done: bool
    done_at: datetime | None
    done_by_user_id: int | None
    sort_order: int
    pending_approval: bool
    created_at: datetime
    updated_at: datetime


class ListItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=280)
    qty: float | None = Field(None, ge=0)
    unit: str | None = Field(None, max_length=24)
    notes: str | None = Field(None, max_length=2000)


class ListItemUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=280)
    qty: float | None = None
    unit: str | None = None
    notes: str | None = None
    done: bool | None = None
    sort_order: int | None = None


class PendingApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requested_by_user_id: int
    supervisor_user_id: int | None
    target_kind: str
    target_id: int | None
    target_payload: dict[str, Any] | None
    state: str
    expires_at: datetime
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


# ─── Helpers ─────────────────────────────────────────────────────────


def _is_child_or_teen(user: User) -> bool:
    return getattr(user, "role", "guest") in {"child", "teen"}


async def _find_supervisor(session: AsyncSession, requester: User) -> int | None:
    """Trova un supervisor (is_supervisor=true) attivo per il
    requester. Single-family stack: il primo trovato vince."""
    stmt = (
        select(User)
        .where(
            getattr(User, "is_supervisor", False).is_(True),
            User.is_active.is_(True),
            User.id != requester.id,
        )
        .order_by(User.created_at.asc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    return row.id if row else None


async def _publish_event(kind: str, payload: dict[str, Any]) -> None:
    """Pubblica evento sul family-bus per real-time UI updates."""
    try:
        from cara.services import family_bus  # noqa: PLC0415

        await family_bus.publish(kind, payload=payload)
    except Exception as exc:  # noqa: BLE001 — best-effort
        log.warning("lifeops.publish_failed", error=str(exc), kind=kind)


# ─── Lists endpoints ─────────────────────────────────────────────────


@router.get("/lists", response_model=list[ListOut])
async def list_lists(
    scope: Literal["user", "family", "all"] = "all",
    archived: bool = False,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ListOut]:
    """Ritorna le liste visibili: sempre le user-scope proprie,
    opzionalmente le family-scope (single-family stack)."""
    stmt = select(LifeopsList).where(LifeopsList.deleted_at.is_(None))
    if not archived:
        stmt = stmt.where(LifeopsList.archived_at.is_(None))
    if scope == "user":
        stmt = stmt.where(
            LifeopsList.user_id == user.id, LifeopsList.scope == "user"
        )
    elif scope == "family":
        stmt = stmt.where(LifeopsList.scope.in_(("family", "shared")))
    else:  # all
        stmt = stmt.where(
            (LifeopsList.user_id == user.id) | (LifeopsList.scope.in_(("family", "shared")))
        )
    stmt = stmt.order_by(LifeopsList.sort_order.asc(), LifeopsList.created_at.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return [ListOut.model_validate(r) for r in rows]


@router.post("/lists", response_model=ListOut, status_code=201)
async def create_list(
    body: ListCreate,
    request: Request,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ListOut:
    new_list = LifeopsList(
        user_id=user.id,
        slug=body.slug,
        title=body.title,
        icon=body.icon,
        scope=body.scope,
        color_token=body.color_token,
    )
    session.add(new_list)
    try:
        await session.flush()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        # UNIQUE constraint violation tipica
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"slug '{body.slug}' già esistente per questo utente",
        ) from exc

    await audit_svc.record(
        session,
        actor=user,
        action="lifeops.list.create",
        target_kind="lifeops_list",
        target_id=str(new_list.id),
        detail={"slug": body.slug, "scope": body.scope},
        ip=request.client.host if request.client else None,
    )
    out = ListOut.model_validate(new_list)
    await _publish_event("lifeops.list.created", out.model_dump(mode="json"))
    return out


@router.patch("/lists/{list_id}", response_model=ListOut)
async def update_list(
    list_id: int,
    body: ListUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ListOut:
    obj = await session.get(LifeopsList, list_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "list not found")
    if obj.scope == "user" and obj.user_id != user.id:
        raise HTTPException(403, "not allowed")

    if body.title is not None:
        obj.title = body.title
    if body.icon is not None:
        obj.icon = body.icon
    if body.color_token is not None:
        obj.color_token = body.color_token
    if body.sort_order is not None:
        obj.sort_order = body.sort_order
    if body.archived is not None:
        obj.archived_at = datetime.now(timezone.utc) if body.archived else None
    obj.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return ListOut.model_validate(obj)


@router.delete("/lists/{list_id}", status_code=204)
async def delete_list(
    list_id: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    obj = await session.get(LifeopsList, list_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "list not found")
    if obj.user_id != user.id:
        raise HTTPException(403, "only owner can delete")
    obj.deleted_at = datetime.now(timezone.utc)
    obj.updated_at = obj.deleted_at
    await session.flush()


# ─── List items endpoints ────────────────────────────────────────────


@router.get("/lists/{list_id}/items", response_model=list[ListItemOut])
async def list_items(
    list_id: int,
    include_done: bool = True,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ListItemOut]:
    parent = await session.get(LifeopsList, list_id)
    if parent is None or parent.deleted_at is not None:
        raise HTTPException(404, "list not found")
    # Access check: user-scope solo proprietario, family-scope tutti.
    if parent.scope == "user" and parent.user_id != user.id:
        raise HTTPException(403, "not allowed")

    stmt = select(LifeopsListItem).where(
        LifeopsListItem.list_id == list_id,
        LifeopsListItem.deleted_at.is_(None),
    )
    if not include_done:
        stmt = stmt.where(LifeopsListItem.done.is_(False))
    stmt = stmt.order_by(
        LifeopsListItem.sort_order.asc(),
        LifeopsListItem.created_at.asc(),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [ListItemOut.model_validate(r) for r in rows]


@router.post("/lists/{list_id}/items", response_model=ListItemOut, status_code=201)
async def add_item(
    list_id: int,
    body: ListItemCreate,
    request: Request,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ListItemOut:
    parent = await session.get(LifeopsList, list_id)
    if parent is None or parent.deleted_at is not None:
        raise HTTPException(404, "list not found")
    if parent.scope == "user" and parent.user_id != user.id:
        raise HTTPException(403, "not allowed")

    # Pending approval per child/teen su lista family
    needs_approval = _is_child_or_teen(user) and parent.scope in (
        "family",
        "shared",
    )

    new_item = LifeopsListItem(
        list_id=list_id,
        user_id=user.id,
        title=body.title,
        qty=body.qty,
        unit=body.unit,
        notes=body.notes,
        pending_approval=needs_approval,
    )
    session.add(new_item)
    await session.flush()

    if needs_approval:
        sup_id = await _find_supervisor(session, user)
        pending = LifeopsPendingApproval(
            requested_by_user_id=user.id,
            supervisor_user_id=sup_id,
            target_kind="list_item",
            target_id=new_item.id,
            target_payload={
                "list_id": list_id,
                "list_title": parent.title,
                "item_title": body.title,
            },
            expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        )
        session.add(pending)
        await session.flush()
        await _publish_event(
            "lifeops.pending.created",
            {
                "id": pending.id,
                "supervisor_user_id": sup_id,
                "target_kind": "list_item",
            },
        )

    await audit_svc.record(
        session,
        actor=user,
        action="lifeops.list_item.add",
        target_kind="lifeops_list_item",
        target_id=str(new_item.id),
        detail={"list_id": list_id, "pending_approval": needs_approval},
        ip=request.client.host if request.client else None,
    )
    out = ListItemOut.model_validate(new_item)
    await _publish_event("lifeops.list_item.added", out.model_dump(mode="json"))
    return out


@router.patch(
    "/lists/{list_id}/items/{item_id}", response_model=ListItemOut
)
async def update_item(
    list_id: int,
    item_id: int,
    body: ListItemUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ListItemOut:
    item = await session.get(LifeopsListItem, item_id)
    if (
        item is None
        or item.list_id != list_id
        or item.deleted_at is not None
    ):
        raise HTTPException(404, "item not found")
    parent = await session.get(LifeopsList, list_id)
    if parent is None or parent.deleted_at is not None:
        raise HTTPException(404, "list not found")
    if parent.scope == "user" and parent.user_id != user.id:
        raise HTTPException(403, "not allowed")

    if body.title is not None:
        item.title = body.title
    if body.qty is not None:
        item.qty = body.qty
    if body.unit is not None:
        item.unit = body.unit
    if body.notes is not None:
        item.notes = body.notes
    if body.done is not None:
        item.done = body.done
        item.done_at = datetime.now(timezone.utc) if body.done else None
        item.done_by_user_id = user.id if body.done else None
    if body.sort_order is not None:
        item.sort_order = body.sort_order
    item.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return ListItemOut.model_validate(item)


@router.delete("/lists/{list_id}/items/{item_id}", status_code=204)
async def delete_item(
    list_id: int,
    item_id: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    item = await session.get(LifeopsListItem, item_id)
    if (
        item is None
        or item.list_id != list_id
        or item.deleted_at is not None
    ):
        raise HTTPException(404, "item not found")
    parent = await session.get(LifeopsList, list_id)
    if parent is None or parent.deleted_at is not None:
        raise HTTPException(404, "list not found")
    if parent.scope == "user" and parent.user_id != user.id:
        raise HTTPException(403, "not allowed")
    item.deleted_at = datetime.now(timezone.utc)
    item.updated_at = item.deleted_at
    await session.flush()


# ─── Pending approvals endpoints ─────────────────────────────────────


@router.get("/pending", response_model=list[PendingApprovalOut])
async def list_pending(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[PendingApprovalOut]:
    """Pending approvals dove l'utente corrente è supervisor (o tutti
    se is_supervisor=true)."""
    stmt = (
        select(LifeopsPendingApproval)
        .where(
            LifeopsPendingApproval.state == "pending",
            LifeopsPendingApproval.expires_at > datetime.now(timezone.utc),
        )
        .order_by(LifeopsPendingApproval.created_at.desc())
    )
    is_super = bool(getattr(user, "is_supervisor", False))
    if not is_super:
        stmt = stmt.where(LifeopsPendingApproval.supervisor_user_id == user.id)
    rows = (await session.execute(stmt)).scalars().all()
    return [PendingApprovalOut.model_validate(r) for r in rows]


@router.post("/pending/{pending_id}/approve", response_model=PendingApprovalOut)
async def approve_pending(
    pending_id: int,
    request: Request,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PendingApprovalOut:
    pending = await session.get(LifeopsPendingApproval, pending_id)
    if pending is None or pending.state != "pending":
        raise HTTPException(404, "pending not found")
    if not bool(getattr(user, "is_supervisor", False)):
        raise HTTPException(403, "solo supervisor possono approvare")

    pending.state = "approved"
    pending.decided_at = datetime.now(timezone.utc)
    pending.updated_at = pending.decided_at

    # Side effect: clear pending_approval flag su target se è list_item
    if pending.target_kind == "list_item" and pending.target_id is not None:
        item = await session.get(LifeopsListItem, pending.target_id)
        if item:
            item.pending_approval = False
            item.updated_at = datetime.now(timezone.utc)

    await session.flush()
    await audit_svc.record(
        session,
        actor=user,
        action="lifeops.pending.approve",
        target_kind="lifeops_pending_approval",
        target_id=str(pending.id),
        ip=request.client.host if request.client else None,
    )
    out = PendingApprovalOut.model_validate(pending)
    await _publish_event("lifeops.pending.approved", out.model_dump(mode="json"))
    return out


@router.post("/pending/{pending_id}/reject", response_model=PendingApprovalOut)
async def reject_pending(
    pending_id: int,
    request: Request,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PendingApprovalOut:
    pending = await session.get(LifeopsPendingApproval, pending_id)
    if pending is None or pending.state != "pending":
        raise HTTPException(404, "pending not found")
    if not bool(getattr(user, "is_supervisor", False)):
        raise HTTPException(403, "solo supervisor possono rifiutare")

    pending.state = "rejected"
    pending.decided_at = datetime.now(timezone.utc)
    pending.updated_at = pending.decided_at

    if pending.target_kind == "list_item" and pending.target_id is not None:
        item = await session.get(LifeopsListItem, pending.target_id)
        if item:
            # Soft delete the requested item
            item.deleted_at = datetime.now(timezone.utc)
            item.updated_at = item.deleted_at

    await session.flush()
    await audit_svc.record(
        session,
        actor=user,
        action="lifeops.pending.reject",
        target_kind="lifeops_pending_approval",
        target_id=str(pending.id),
        ip=request.client.host if request.client else None,
    )
    return PendingApprovalOut.model_validate(pending)
