"""Conversation CRUD endpoints — scoped to the authenticated user."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
)
from cara.services import conversations as svc
from cara.store import get_session

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ConversationOut]:
    rows = await svc.list_conversations(session, user_id=user.id)
    return [ConversationOut.model_validate(r) for r in rows]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ConversationOut:
    convo = await svc.create_conversation(session, user_id=user.id, title=body.title)
    return ConversationOut.model_validate(convo)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ConversationDetail:
    convo = await svc.get_conversation(session, conversation_id, user_id=user.id)
    if convo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return ConversationDetail.model_validate(convo)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await svc.delete_conversation(session, conversation_id, user_id=user.id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
