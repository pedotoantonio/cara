"""Web Push delivery service.

Wraps `pywebpush` so the rest of the codebase can fire-and-forget
notifications without dealing with VAPID details. Two responsibilities:

1. **Send**: encrypt payload + sign with VAPID + POST to the push service
   (Mozilla, Apple, Google, …) chosen by the subscription endpoint URL.
2. **Cleanup on failure**: 404/410 from the push service means the
   browser revoked the subscription — we delete the row so the next
   scan doesn't waste cycles trying to re-deliver.

Pure async. No global state outside of `settings` import.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog
from pywebpush import WebPushException, webpush
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from cara.config import settings
from cara.models.push_subscription import PushSubscription


log = structlog.get_logger(__name__)


class PushNotConfigured(Exception):
    """Raised at the call site when VAPID keys are missing."""


@dataclass
class PushPayload:
    """Shape sent to the SW. Frontend reads `title`, `body`, `tag`, `url`."""

    title: str
    body: str
    tag: str | None = None
    url: str | None = None
    icon: str | None = None
    badge: str | None = None

    def as_json(self) -> str:
        return json.dumps(
            {
                "title": self.title,
                "body": self.body,
                "tag": self.tag,
                "url": self.url,
                "icon": self.icon or "/icon-192.png",
                "badge": self.badge or "/icon-192.png",
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )


def is_configured() -> bool:
    return bool(settings.vapid_private_key and settings.vapid_public_key)


async def send_to_subscription(
    session: AsyncSession,
    sub: PushSubscription,
    payload: PushPayload,
    *,
    ttl_seconds: int = 3600,
) -> bool:
    """Encrypt + send `payload` to one subscription.

    Returns True on success, False on permanent failure (subscription
    deleted automatically). Network blips are surfaced as False but the
    subscription is kept for the next attempt.
    """
    if not is_configured():
        raise PushNotConfigured("VAPID keys not set; cannot send push")

    sub_info = {
        "endpoint": sub.endpoint,
        "keys": {"p256dh": sub.p256dh, "auth": sub.auth_secret},
    }

    try:
        webpush(
            subscription_info=sub_info,
            data=payload.as_json(),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_contact_email},
            ttl=ttl_seconds,
        )
        return True
    except WebPushException as exc:
        # Distinguish a dead subscription (must purge) from transient
        # network issues (worth retrying next tick).
        status = getattr(exc.response, "status_code", None) if exc.response else None
        # Fallback: the SDK sometimes wraps the response so `.status_code`
        # is None even though the message embeds "Push failed: 410 …".
        # Pattern-match the message to recover the dead-subscription case.
        if status is None:
            msg = str(exc).lower()
            if "410 gone" in msg or "404 not found" in msg or "unsubscribed or expired" in msg:
                status = 410
        if status in (404, 410):
            log.info(
                "push.subscription_gone",
                endpoint=_endpoint_short(sub.endpoint),
                status=status,
            )
            await session.execute(
                delete(PushSubscription).where(PushSubscription.id == sub.id)
            )
            await session.commit()
            return False
        log.warning(
            "push.send_failed",
            endpoint=_endpoint_short(sub.endpoint),
            status=status,
            error=str(exc),
        )
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "push.send_unexpected_error",
            endpoint=_endpoint_short(sub.endpoint),
            error=str(exc),
        )
        return False


async def send_to_user(
    session: AsyncSession,
    user_id: int,
    payload: PushPayload,
) -> int:
    """Fan-out: send to every active subscription for `user_id`. Returns
    the number of devices we successfully delivered to."""
    if not is_configured():
        log.info("push.skipped_unconfigured", user_id=user_id)
        return 0

    from sqlalchemy import select

    rows = (
        await session.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
    ).scalars().all()
    if not rows:
        return 0

    delivered = 0
    for sub in list(rows):
        ok = await send_to_subscription(session, sub, payload)
        if ok:
            delivered += 1
            sub.last_pushed_at = _now_aware()
    if delivered:
        await session.commit()
    return delivered


def _endpoint_short(url: str) -> str:
    """Short form for logs — domain only, no token tail."""
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc
    except Exception:  # noqa: BLE001
        return url[:40]


def _now_aware():  # noqa: ANN202
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
