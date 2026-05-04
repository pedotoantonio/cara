"""Unit tests for `cara.services.response_cache`.

We don't talk to a real Redis here — a tiny in-memory fake replicates the
five methods the cache uses (`get`, `set`, `delete`, `scan`).
"""

from __future__ import annotations

from typing import Any

import pytest

from cara.services.response_cache import (
    CachedResponse,
    ResponseCache,
    derive_key,
    is_time_sensitive,
)

# pytestmark intentionally NOT pytest.mark.asyncio at module scope:
# the parametrised heuristic tests below are sync. Each async test
# carries its own marker via pytest-asyncio's auto mode.


class FakeRedis:
    """Minimal async-redis stand-in supporting the methods we use."""

    def __init__(self) -> None:
        self.store: dict[bytes, bytes] = {}
        self.fail_get = False
        self.fail_set = False

    async def get(self, key: str | bytes):  # noqa: ANN001
        if self.fail_get:
            raise RuntimeError("redis down")
        if isinstance(key, str):
            key = key.encode()
        return self.store.get(key)

    async def set(self, key, value, *, ex=None):  # noqa: ANN001, ARG002
        if self.fail_set:
            raise RuntimeError("redis down")
        if isinstance(key, str):
            key = key.encode()
        if isinstance(value, str):
            value = value.encode()
        self.store[key] = value
        return True

    async def delete(self, key):  # noqa: ANN001
        if isinstance(key, str):
            key = key.encode()
        self.store.pop(key, None)
        return 1

    async def scan(self, *, cursor=b"0", match=None, count=100):  # noqa: ANN001, ARG002
        # One-shot iterator: returns all matching keys, then cursor=0.
        prefix = match.replace("*", "") if match else ""
        if isinstance(prefix, str):
            prefix = prefix.encode()
        keys = [k for k in self.store if k.startswith(prefix)]
        return (b"0", keys)


# ---------------------------------------------------------------- derive_key


def test_derive_key_is_stable_for_same_input() -> None:
    a = derive_key(message="che ore sono", user_id=1, role="parent")
    b = derive_key(message="che ore sono", user_id=1, role="parent")
    assert a == b


def test_derive_key_normalises_whitespace_and_case() -> None:
    a = derive_key(message="Che Ore Sono?", user_id=1, role="parent")
    b = derive_key(message="che    ore  sono?", user_id=1, role="parent")
    assert a == b


def test_derive_key_differs_per_user() -> None:
    a = derive_key(message="ciao", user_id=1, role="parent")
    b = derive_key(message="ciao", user_id=2, role="parent")
    assert a != b


def test_derive_key_differs_per_role() -> None:
    a = derive_key(message="ciao", user_id=1, role="parent")
    b = derive_key(message="ciao", user_id=1, role="child")
    assert a != b


def test_derive_key_changes_when_relevant_setting_changes() -> None:
    a = derive_key(
        message="ciao", user_id=1, settings={"llm_quality_mode": "fast"}
    )
    b = derive_key(
        message="ciao", user_id=1, settings={"llm_quality_mode": "quality"}
    )
    assert a != b


def test_derive_key_ignores_unrelated_settings() -> None:
    """Adding settings that don't materially change the response shape
    should not invalidate the cache key — otherwise admin tweaks blow
    away every entry."""
    a = derive_key(message="ciao", user_id=1, settings={"some_unrelated_flag": True})
    b = derive_key(message="ciao", user_id=1, settings={"some_other_flag": False})
    c = derive_key(message="ciao", user_id=1)
    assert a == b == c


# ---------------------------------------------------------------- CachedResponse


def test_cached_response_round_trip() -> None:
    cr = CachedResponse(text="ciao", meta={"tool": "none", "user_id": 7})
    raw = cr.to_json()
    back = CachedResponse.from_json(raw)
    assert back is not None
    assert back.text == "ciao"
    assert back.meta == {"tool": "none", "user_id": 7}


def test_cached_response_rejects_corrupt_json() -> None:
    assert CachedResponse.from_json("not json") is None
    assert CachedResponse.from_json('{"schema": 999}') is None  # wrong schema


# ---------------------------------------------------------------- ResponseCache


async def test_set_then_get_returns_value() -> None:
    fake = FakeRedis()
    cache = ResponseCache(fake)
    key = derive_key(message="ciao", user_id=1, role="parent")

    assert await cache.get(key) is None
    assert await cache.set(key, "ciao Antonio") is True

    cached = await cache.get(key)
    assert cached is not None
    assert cached.text == "ciao Antonio"


async def test_set_persists_meta() -> None:
    fake = FakeRedis()
    cache = ResponseCache(fake)
    key = derive_key(message="ciao", user_id=1)
    await cache.set(key, "hi", meta={"tool": "none", "stage": "fastpath"})

    cached = await cache.get(key)
    assert cached is not None
    assert cached.meta == {"tool": "none", "stage": "fastpath"}


async def test_get_redis_failure_returns_none() -> None:
    fake = FakeRedis()
    fake.fail_get = True
    cache = ResponseCache(fake)
    key = derive_key(message="ciao", user_id=1)
    # Must NOT raise — failures degrade silently.
    assert await cache.get(key) is None


async def test_set_redis_failure_returns_false_no_raise() -> None:
    fake = FakeRedis()
    fake.fail_set = True
    cache = ResponseCache(fake)
    key = derive_key(message="ciao", user_id=1)
    assert await cache.set(key, "value") is False


async def test_get_discards_corrupt_payload() -> None:
    fake = FakeRedis()
    cache = ResponseCache(fake)
    key = derive_key(message="ciao", user_id=1)
    fake.store[key.encode()] = b"not-json-at-all"

    cached = await cache.get(key)
    assert cached is None
    # Corrupt entry should be cleaned up so the next get_or_compute can
    # repopulate it.
    assert key.encode() not in fake.store


async def test_invalidate_removes_key() -> None:
    fake = FakeRedis()
    cache = ResponseCache(fake)
    key = derive_key(message="ciao", user_id=1)
    await cache.set(key, "v")
    await cache.invalidate(key)
    assert await cache.get(key) is None


async def test_invalidate_user_removes_only_their_entries() -> None:
    fake = FakeRedis()
    cache = ResponseCache(fake)

    k1 = derive_key(message="m1", user_id=1)
    k2 = derive_key(message="m2", user_id=2)
    await cache.set(k1, "for_one", meta={"user_id": 1})
    await cache.set(k2, "for_two", meta={"user_id": 2})

    deleted = await cache.invalidate_user(1)
    assert deleted == 1
    assert await cache.get(k1) is None
    assert (await cache.get(k2)) is not None


# ---------------------------------------------------------------- time-sensitive heuristic


@pytest.mark.parametrize("msg", [
    "che ore sono?",
    "chi è in casa adesso?",
    "che cosa fa stasera?",
    "ricordami le notizie",
    "metti la radio",
    "domani che tempo fa",
    "stamattina presto",
    "la lista delle tasks di oggi",
])
def test_is_time_sensitive_catches_known_phrases(msg: str) -> None:
    assert is_time_sensitive(msg) is True


@pytest.mark.parametrize("msg", [
    "raccontami una barzelletta",
    "spiegami cos'è la fotosintesi",
    "ricetta della carbonara",
    "come si dice 'mela' in inglese",
    "cosa è un buco nero",
])
def test_is_time_sensitive_lets_evergreen_questions_through(msg: str) -> None:
    assert is_time_sensitive(msg) is False
