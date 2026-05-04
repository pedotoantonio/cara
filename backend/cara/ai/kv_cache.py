"""RKLLM prompt-cache (KV cache) helpers.

The RKLLM v1.1.0 runtime supports persisting the KV cache for a generation
to a binary file (`save_prompt_cache=1` + `prompt_cache_path`), and re-using
it on the next `rkllm_run` call to skip prefill. This module gives the rest
of CARA a stable per-conversation cache filename plus the operational
helpers for invalidation and cleanup.

Per-process strategy:

- One file per `(conversation_id)` in `data/kv_cache/<sha1(conv_id)>.bin`
- File written by RKLLM at the end of generation (it overwrites in place)
- Cache is invalidated when the conversation's effective system prompt
  changes — the chat layer is responsible for calling `flush_one(conv_id)`
  on prompt mutation.
- A janitor cron (`cleanup_stale`, default 30-minute idle TTL) prevents
  unbounded disk growth in case a conversation goes silent.

The cache path returned by `path_for_conversation()` is created lazily —
the first generation that uses a given conversation sees the file appear
on disk; subsequent generations on the same conversation re-use it.

This module is dependency-free (no rk bindings, no SQLAlchemy). It just
hands callers a Path object and the bookkeeping. The actual `infer.
prompt_cache_params` plumbing happens in `cara.ai.llm.LLMService.generate`.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Iterable

import structlog


log = structlog.get_logger(__name__)


# Default location matches the docker-compose volume mount layout
# (`./data/kv_cache:/app/cache/kv`). Override via env in production by
# passing `cache_dir=` to the helpers.
DEFAULT_CACHE_DIR = Path("/app/cache/kv")


def _hash_conv_id(conv_id: str) -> str:
    """Deterministic short hash so the on-disk filename has no PII."""
    return hashlib.sha1(conv_id.encode("utf-8")).hexdigest()[:24]


def path_for_conversation(
    conv_id: str | None,
    *,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> Path | None:
    """Compute the canonical cache path for `conv_id`.

    Returns None if `conv_id` is None / empty — the caller passes that
    None straight through to `LLMService.generate` and gets
    cache-disabled behaviour, just like before.

    Creates the parent directory on first call. Idempotent.
    """
    if not conv_id:
        return None
    cache_dir = Path(cache_dir)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("kv_cache.mkdir_failed", path=str(cache_dir), error=str(exc))
        return None
    return cache_dir / f"{_hash_conv_id(conv_id)}.bin"


# ---------------------------------------------------------------------------
# Operational helpers
# ---------------------------------------------------------------------------


def flush_one(
    conv_id: str,
    *,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> bool:
    """Delete the cache file for `conv_id`. Returns True if a file existed.

    Called whenever the conversation's prefix changes shape:
    - admin tweaks the runtime system prompt
    - user manually clears chat history
    - tone / role / privacy mode change for that conversation
    """
    p = path_for_conversation(conv_id, cache_dir=cache_dir)
    if p is None or not p.exists():
        return False
    try:
        p.unlink()
        log.info("kv_cache.flushed", conv_id_hash=_hash_conv_id(conv_id))
        return True
    except OSError as exc:
        log.warning("kv_cache.flush_failed",
                    conv_id_hash=_hash_conv_id(conv_id), error=str(exc))
        return False


def flush_many(
    conv_ids: Iterable[str],
    *,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> int:
    """Bulk flush. Returns number of files removed."""
    return sum(1 for cid in conv_ids if flush_one(cid, cache_dir=cache_dir))


def flush_all(
    *,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> int:
    """Wipe every cache entry. Returns number of files removed.

    Use sparingly: every active conversation pays a one-turn TTFT
    penalty after this. Justified when the GLOBAL system prompt changes.
    """
    cache_dir = Path(cache_dir)
    if not cache_dir.exists():
        return 0
    n = 0
    for p in cache_dir.glob("*.bin"):
        try:
            p.unlink()
            n += 1
        except OSError:
            continue
    if n:
        log.info("kv_cache.flush_all", removed=n)
    return n


def cleanup_stale(
    *,
    idle_seconds: int = 30 * 60,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> int:
    """Delete cache files whose mtime is older than `idle_seconds`.

    Designed to run as a Celery beat task. Default 30 minutes — long
    enough to span a normal coffee break, short enough to keep disk
    usage bounded for an idle family.
    """
    cache_dir = Path(cache_dir)
    if not cache_dir.exists():
        return 0
    threshold = time.time() - idle_seconds
    removed = 0
    for p in cache_dir.glob("*.bin"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime < threshold:
            try:
                p.unlink()
                removed += 1
            except OSError:
                continue
    if removed:
        log.info("kv_cache.cleanup_stale", removed=removed,
                 idle_seconds=idle_seconds)
    return removed


def cache_size_bytes(
    *,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> int:
    """Total disk used by KV cache, in bytes. For admin diagnostics."""
    cache_dir = Path(cache_dir)
    if not cache_dir.exists():
        return 0
    total = 0
    for p in cache_dir.glob("*.bin"):
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return total


def reset_for_test(cache_dir: Path | str) -> None:
    """Remove the entire test cache directory."""
    cache_dir = Path(cache_dir)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
