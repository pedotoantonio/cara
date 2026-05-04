"""Redis-backed response cache for cheap, repeatable chat queries.

Not every chat turn needs to round-trip the LLM. Questions like "che ore
sono?", "chi è in casa?" or "ricordami cosa devo fare oggi" are answered
the same way most of the time — caching them for a few minutes shaves
latency and frees the NPU for genuinely new questions.

This module is the cache *layer*. The decision of WHICH responses to
cache (the policy) lives in the chat handler / pipeline stage that
wraps it. The cache itself takes a key, accepts a value, returns a
value or None. Nothing more.

Key derivation:

    key = sha256( norm(message) | user_id | role | settings_fingerprint )

Reasons each component is in the key:

- `norm(message)`: lower-cased, whitespace-collapsed user message. Two
  visually different inputs that mean the same thing collapse to one key.
- `user_id`: cache hits between users would leak personalised answers.
- `role`: same user message, different role (parent vs child) → different
  tone, different answer.
- `settings_fingerprint`: a hash of the runtime settings that materially
  affect the response (system prompt id, llm quality mode, tone
  directive). Settings change → caches invalidate naturally.

Time-sensitive content (who_is_home, get_news, weather, time-of-day) is
NOT cached — the policy in the chat layer marks those queries
`bypass_cache=True`.

Stored value is JSON-serialisable (response text + meta). Compressed at
the application layer if it ever gets big — for now JSON is fine.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog


log = structlog.get_logger(__name__)


_KEY_PREFIX = "cara:resp:"
_DEFAULT_TTL_SECONDS = 300
_VERSION = 1  # bump if the cache shape changes


_WS_RE = re.compile(r"\s+")


def _normalise_message(text: str) -> str:
    """Aggressive lowercase + whitespace collapse so trivial typing
    differences hit the same cache slot."""
    return _WS_RE.sub(" ", text.strip().lower())


_RELEVANT_SETTINGS = (
    "llm_quality_mode",
    "system_prompt_id",
    "tone_directive",
    "validation_enabled",
    "cognitive_mode",
)


def _settings_fingerprint(settings: Mapping[str, Any] | None) -> str:
    """A stable hash of the settings keys that change the response shape.

    Whitelisted keys only — adding new settings shouldn't accidentally
    invalidate the entire cache. If none of the relevant keys is present,
    we collapse to the "default" sentinel so passing `{}` and `None` and
    `{"unrelated": ...}` all hit the same cache slot.
    """
    if not settings:
        return "default"
    fp = {k: settings[k] for k in _RELEVANT_SETTINGS if k in settings}
    if not fp:
        return "default"
    return hashlib.sha256(
        json.dumps(fp, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def derive_key(
    *,
    message: str,
    user_id: int | None,
    role: str = "guest",
    settings: Mapping[str, Any] | None = None,
) -> str:
    """Compute the canonical cache key for a request."""
    parts = (
        f"v{_VERSION}",
        _normalise_message(message),
        str(user_id if user_id is not None else "anon"),
        role or "guest",
        _settings_fingerprint(settings),
    )
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


@dataclass
class CachedResponse:
    """The serialised payload we write to Redis."""

    text: str
    meta: dict[str, Any] = field(default_factory=dict)
    cached_at: float = field(default_factory=time.time)
    schema: int = _VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, raw: str | bytes) -> CachedResponse | None:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if data.get("schema") != _VERSION:
            return None
        try:
            return cls(
                text=data["text"],
                meta=data.get("meta", {}) or {},
                cached_at=float(data.get("cached_at", time.time())),
                schema=int(data["schema"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


class ResponseCache:
    """Thin facade over a redis.asyncio client.

    All Redis errors are swallowed and turned into "cache miss" / "store
    no-op" — the cache must NEVER be on the critical path of a chat
    request. If Redis goes down, chat keeps working, just slower.
    """

    def __init__(self, redis_client, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:  # noqa: ANN001
        self._redis = redis_client
        self._ttl = max(1, int(ttl_seconds))

    async def get(self, key: str) -> CachedResponse | None:
        try:
            raw = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001 — never break the hot path
            log.warning("response_cache.get.failed", key=key, error=str(exc))
            return None
        if raw is None:
            return None
        cached = CachedResponse.from_json(raw)
        if cached is None:
            log.info("response_cache.discard_corrupt", key=key)
            try:
                await self._redis.delete(key)
            except Exception:  # noqa: BLE001
                pass
            return None
        return cached

    async def set(
        self,
        key: str,
        text: str,
        *,
        meta: Mapping[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Store a response. Returns True on success, False on any error."""
        payload = CachedResponse(text=text, meta=dict(meta or {}))
        try:
            await self._redis.set(
                key,
                payload.to_json(),
                ex=ttl_seconds or self._ttl,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("response_cache.set.failed", key=key, error=str(exc))
            return False

    async def invalidate(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("response_cache.invalidate.failed", key=key, error=str(exc))

    async def invalidate_user(self, user_id: int) -> int:
        """Invalidate every cached response belonging to a user.

        Implementation note: the user_id is part of the SHA256 key so we
        can't reverse it. We instead use a SCAN over the prefix and a
        secondary mapping. To keep this module dependency-free we just
        iterate via SCAN over the full prefix and delete keys whose
        stored payload mentions the user — this is rare (called on
        purge / role change), so the linear scan is fine.

        Returns the number of keys deleted.
        """
        deleted = 0
        try:
            cursor = b"0"
            while cursor:
                cursor, keys = await self._redis.scan(
                    cursor=cursor, match=f"{_KEY_PREFIX}*", count=200
                )
                for k in keys:
                    raw = await self._redis.get(k)
                    if raw is None:
                        continue
                    try:
                        body = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if body.get("meta", {}).get("user_id") == user_id:
                        await self._redis.delete(k)
                        deleted += 1
                if cursor in (0, b"0"):
                    break
        except Exception as exc:  # noqa: BLE001
            log.warning("response_cache.invalidate_user.failed", error=str(exc))
        return deleted


# Heuristics: a query that mentions any of these words/intents is
# time-sensitive and SHOULD NOT be cached. Conservative: better not cache
# something cacheable than cache something stale.
_TIME_SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:adesso|ora|ore|orari[oa]|che\s+ore)\b", re.IGNORECASE),
    re.compile(r"\boggi\b", re.IGNORECASE),
    re.compile(r"\b(?:domani|ieri|stasera|stamattina)\b", re.IGNORECASE),
    re.compile(r"\bchi\s+(?:è|c[''])\s*in\s+casa\b", re.IGNORECASE),
    re.compile(r"\bmeteo\b|\btempo\b.*\b(?:fa|farà|domani)\b", re.IGNORECASE),
    re.compile(r"\bnotizi[ae]\b|\bnews\b|\bultim[ie]\s+notizi[ae]\b", re.IGNORECASE),
    re.compile(r"\bradio\b", re.IGNORECASE),
    re.compile(r"\b(?:tasks?|note|spes[ae])\b.*\b(?:lista|elenco)\b", re.IGNORECASE),
)


def is_time_sensitive(message: str) -> bool:
    """True if the message asks about a fast-changing fact and should bypass cache."""
    for pat in _TIME_SENSITIVE_PATTERNS:
        if pat.search(message):
            return True
    return False
