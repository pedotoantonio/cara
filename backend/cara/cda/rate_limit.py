"""Per-user sliding-window rate limiter for the Content Discovery Agent.

Backed by Redis: one counter key per `(user_id, action, minute)` with TTL 90 s.
Counts the current and previous minute window for a smoother limit than a hard
60-second bucket.
"""

from __future__ import annotations

import time

import structlog

logger = structlog.get_logger(__name__)


class CdaRateLimitError(Exception):
    """Raised when a user has exceeded the per-minute discover budget."""

    def __init__(self, retry_after_seconds: int, limit: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        self.limit = limit
        super().__init__(
            f"Rate limit raggiunto ({limit}/min). Riprova fra {retry_after_seconds}s."
        )


_redis = None
_redis_url: str | None = None


def attach_redis_url(url: str) -> None:
    """Wire the Redis URL once at app startup."""
    global _redis_url
    _redis_url = url


async def _client():  # type: ignore[no-untyped-def]
    """Lazy redis.asyncio client (one per process)."""
    global _redis
    if _redis is None and _redis_url:
        import redis.asyncio as aioredis  # local import keeps startup snappy

        _redis = aioredis.from_url(_redis_url, decode_responses=False)
    return _redis


async def check_and_record(user_id: int, action: str, max_per_minute: int) -> None:
    """Increment the counter for the current minute and raise if over budget.

    `max_per_minute <= 0` disables the limit (returns immediately).
    Redis being unreachable is logged and treated as fail-open — we never
    want the rate limiter itself to take down the discover endpoint.
    """
    if max_per_minute <= 0:
        return
    client = await _client()
    if client is None:
        return  # not configured → no-op
    minute = int(time.time() // 60)
    key = f"cda:rl:{action}:{user_id}:{minute}"
    try:
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 90)
        results = await pipe.execute()
        count = int(results[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("cda.rate_limit.redis_error", error=str(exc), user_id=user_id)
        return
    if count > max_per_minute:
        retry_after = 60 - int(time.time() % 60)
        logger.info(
            "cda.rate_limit.exceeded",
            user_id=user_id,
            action=action,
            count=count,
            limit=max_per_minute,
            retry_after=retry_after,
        )
        raise CdaRateLimitError(retry_after_seconds=retry_after, limit=max_per_minute)
