"""Unit tests for `cara.ai.kv_cache` — pathing + flush + cleanup."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from cara.ai import kv_cache


@pytest.fixture
def tmp_cache(tmp_path: Path) -> Path:
    """A clean cache directory under pytest's tmp_path. Auto-removed."""
    d = tmp_path / "kv_cache"
    yield d
    kv_cache.reset_for_test(d)


def test_path_for_conversation_returns_path_in_cache_dir(tmp_cache: Path) -> None:
    p = kv_cache.path_for_conversation("conv-123", cache_dir=tmp_cache)
    assert p is not None
    assert p.parent == tmp_cache
    assert p.suffix == ".bin"


def test_path_for_conversation_creates_dir(tmp_cache: Path) -> None:
    assert not tmp_cache.exists()
    kv_cache.path_for_conversation("any", cache_dir=tmp_cache)
    assert tmp_cache.exists()


def test_path_for_conversation_returns_none_for_empty_id(tmp_cache: Path) -> None:
    assert kv_cache.path_for_conversation(None, cache_dir=tmp_cache) is None
    assert kv_cache.path_for_conversation("", cache_dir=tmp_cache) is None


def test_path_for_conversation_is_deterministic(tmp_cache: Path) -> None:
    a = kv_cache.path_for_conversation("conv-A", cache_dir=tmp_cache)
    b = kv_cache.path_for_conversation("conv-A", cache_dir=tmp_cache)
    assert a == b


def test_path_for_conversation_anonymises_id(tmp_cache: Path) -> None:
    """The on-disk filename must NOT contain the raw conversation id."""
    p = kv_cache.path_for_conversation("super-secret-conv-id", cache_dir=tmp_cache)
    assert p is not None
    assert "super-secret" not in p.name


def test_path_for_conversation_different_ids_different_paths(tmp_cache: Path) -> None:
    a = kv_cache.path_for_conversation("a", cache_dir=tmp_cache)
    b = kv_cache.path_for_conversation("b", cache_dir=tmp_cache)
    assert a != b


# ---------------------------------------------------------------- flush_one


def test_flush_one_returns_false_when_no_file(tmp_cache: Path) -> None:
    assert kv_cache.flush_one("never-written", cache_dir=tmp_cache) is False


def test_flush_one_removes_existing_file(tmp_cache: Path) -> None:
    p = kv_cache.path_for_conversation("conv-x", cache_dir=tmp_cache)
    assert p is not None
    p.write_bytes(b"fake-cache")

    assert kv_cache.flush_one("conv-x", cache_dir=tmp_cache) is True
    assert not p.exists()


def test_flush_one_handles_empty_id(tmp_cache: Path) -> None:
    """flush_one('') must not crash and just returns False."""
    assert kv_cache.flush_one("", cache_dir=tmp_cache) is False


# ---------------------------------------------------------------- flush_many / flush_all


def test_flush_many_counts_removed(tmp_cache: Path) -> None:
    for cid in ("a", "b", "c"):
        p = kv_cache.path_for_conversation(cid, cache_dir=tmp_cache)
        p.write_bytes(b"x")

    n = kv_cache.flush_many(["a", "b", "missing"], cache_dir=tmp_cache)
    assert n == 2


def test_flush_all_clears_cache(tmp_cache: Path) -> None:
    for cid in ("a", "b", "c"):
        p = kv_cache.path_for_conversation(cid, cache_dir=tmp_cache)
        p.write_bytes(b"x")

    n = kv_cache.flush_all(cache_dir=tmp_cache)
    assert n == 3
    assert list(tmp_cache.glob("*.bin")) == []


def test_flush_all_on_missing_dir_returns_zero(tmp_path: Path) -> None:
    assert kv_cache.flush_all(cache_dir=tmp_path / "no-such-dir") == 0


# ---------------------------------------------------------------- cleanup_stale


def test_cleanup_stale_removes_old_files(tmp_cache: Path) -> None:
    fresh = kv_cache.path_for_conversation("fresh", cache_dir=tmp_cache)
    stale = kv_cache.path_for_conversation("stale", cache_dir=tmp_cache)
    fresh.write_bytes(b"x")
    stale.write_bytes(b"x")

    # Backdate the stale file via os.utime (mtime in the past).
    import os
    old_ts = time.time() - 60 * 60 * 2  # 2 hours ago
    os.utime(stale, (old_ts, old_ts))

    removed = kv_cache.cleanup_stale(idle_seconds=60 * 30, cache_dir=tmp_cache)
    assert removed == 1
    assert fresh.exists()
    assert not stale.exists()


def test_cleanup_stale_keeps_everything_when_all_fresh(tmp_cache: Path) -> None:
    p = kv_cache.path_for_conversation("a", cache_dir=tmp_cache)
    p.write_bytes(b"x")

    removed = kv_cache.cleanup_stale(idle_seconds=60 * 30, cache_dir=tmp_cache)
    assert removed == 0
    assert p.exists()


def test_cleanup_stale_on_missing_dir(tmp_path: Path) -> None:
    assert kv_cache.cleanup_stale(cache_dir=tmp_path / "no-dir") == 0


# ---------------------------------------------------------------- cache_size_bytes


def test_cache_size_bytes_aggregates_files(tmp_cache: Path) -> None:
    a = kv_cache.path_for_conversation("a", cache_dir=tmp_cache)
    b = kv_cache.path_for_conversation("b", cache_dir=tmp_cache)
    a.write_bytes(b"X" * 100)
    b.write_bytes(b"Y" * 200)

    assert kv_cache.cache_size_bytes(cache_dir=tmp_cache) == 300


def test_cache_size_bytes_on_missing_dir(tmp_path: Path) -> None:
    assert kv_cache.cache_size_bytes(cache_dir=tmp_path / "no-dir") == 0
