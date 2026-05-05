"""Web Push API — subscribe / unsubscribe / send-test.

Frontend flow:

  GET  /push/public-key            → returns VAPID public key (or null)
  POST /push/subscribe             → register a PushSubscription
                                     body: {endpoint, keys:{p256dh,auth}, user_agent?}
  DELETE /push/subscribe           → unregister by endpoint
                                     body: {endpoint}
  POST /push/test                  → fire a test notification to current user

All endpoints require auth except `public-key` (which is needed BEFORE
the subscribe call). Public key is non-secret by design.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.config import settings
from cara.models.push_subscription import PushSubscription
from cara.models.user import User
from cara.services.push import PushPayload, is_configured, send_to_user
from cara.store import get_session


log = structlog.get_logger(__name__)
router = APIRouter(prefix="/push", tags=["push"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _PushKeys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=255)
    auth: str = Field(min_length=10, max_length=255)


class SubscribeBody(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2048)
    keys: _PushKeys
    user_agent: str | None = Field(default=None, max_length=255)


class UnsubscribeBody(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2048)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/public-key")
async def get_public_key() -> dict:
    """Return the VAPID public key the SW needs to subscribe.

    Empty string when push is not configured — the frontend should hide
    the subscribe UI in that case.
    """
    return {
        "public_key": settings.vapid_public_key or None,
        "configured": is_configured(),
    }


@router.post("/subscribe")
async def subscribe(
    body: SubscribeBody,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    """Register or refresh a Push subscription for the current user.

    Idempotent on `endpoint`: a second call with the same endpoint
    updates the keys + user_agent + timestamps without creating a
    duplicate row.
    """
    existing = (
        await session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is not None:
        # Re-bind to current user (covers the case of switching accounts
        # on the same device) and refresh credentials.
        existing.user_id = user.id
        existing.p256dh = body.keys.p256dh
        existing.auth_secret = body.keys.auth
        existing.user_agent = body.user_agent
        existing.last_seen_at = now
        await session.commit()
        log.info("push.subscription_updated", id=str(existing.id), user_id=user.id)
        return {"id": str(existing.id), "status": "updated"}

    sub = PushSubscription(
        user_id=user.id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth_secret=body.keys.auth,
        user_agent=body.user_agent,
        last_seen_at=now,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    log.info("push.subscription_created", id=str(sub.id), user_id=user.id)
    return {"id": str(sub.id), "status": "created"}


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    body: UnsubscribeBody = Body(...),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Remove the subscription for `endpoint`. No-op if it doesn't exist
    or doesn't belong to the current user (we don't leak existence)."""
    res = (
        await session.execute(
            select(PushSubscription)
            .where(PushSubscription.endpoint == body.endpoint)
            .where(PushSubscription.user_id == user.id)
        )
    ).scalar_one_or_none()
    if res is None:
        return None
    await session.delete(res)
    await session.commit()
    log.info("push.subscription_deleted", id=str(res.id), user_id=user.id)
    return None


@router.post("/test")
async def send_test_push(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, int | bool]:
    """Send a "ciao" notification to every active device. Used by the
    frontend to verify the subscription works — the user can confirm
    they actually received it on their phone."""
    if not is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Push non configurato (VAPID keys mancanti)",
        )

    delivered = await send_to_user(
        session,
        user_id=user.id,
        payload=PushPayload(
            title="Cara",
            body="Le notifiche funzionano. A presto!",
            tag="cara-test",
            url="/",
        ),
    )
    return {"delivered": delivered, "configured": True}


@router.get("/subscriptions")
async def list_subscriptions(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict]:
    """Return the user's current subscriptions (for the settings UI)."""
    rows = (
        await session.execute(
            select(PushSubscription)
            .where(PushSubscription.user_id == user.id)
            .order_by(PushSubscription.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "user_agent": r.user_agent,
            "created_at": r.created_at.isoformat(),
            "last_pushed_at": r.last_pushed_at.isoformat() if r.last_pushed_at else None,
        }
        for r in rows
    ]
