"""In-memory ring buffer of recent CARA events.

Used by the admin diagnostics page to surface what just happened in the
backend WITHOUT requiring the user to read `docker logs`.

Thread-safe: every chat/router/ASR/TTS branch can call `record(...)` and
the deque mutex serialises appends.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Iterable

# Last N events. Capped to avoid unbounded memory growth when CARA runs
# for weeks; old events fall off the back.
_BUFFER_SIZE = 200

_buffer: deque[dict[str, Any]] = deque(maxlen=_BUFFER_SIZE)
_lock = threading.Lock()


def record(
    kind: str,
    *,
    user_id: int | None = None,
    duration_ms: int | float | None = None,
    **data: Any,
) -> None:
    """Append a structured event to the ring buffer.

    `kind` is the dot-namespaced event name, e.g. "intent_router.match",
    "chat.noise_bypass", "tts.speak", "asr.whisper".

    Any extra kwargs end up in `data` and are JSON-serialised by callers
    of `recent()` (must be plain types, not ORM rows).
    """
    event: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "kind": kind,
        "user_id": user_id,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "data": data or {},
    }
    with _lock:
        _buffer.append(event)


def recent(
    *, limit: int = 100, kinds: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    """Return the most recent events, newest-first, filtered by `kinds`
    if provided. Defensive copy — caller can mutate freely."""
    kinds_set = set(kinds) if kinds else None
    with _lock:
        snapshot = list(_buffer)
    snapshot.reverse()
    if kinds_set is not None:
        snapshot = [e for e in snapshot if e.get("kind") in kinds_set]
    if limit and limit > 0:
        snapshot = snapshot[:limit]
    return snapshot


def stats() -> dict[str, int]:
    """Return per-kind counts across the buffer (for the admin grid)."""
    with _lock:
        snapshot = list(_buffer)
    counts: dict[str, int] = {}
    for e in snapshot:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return counts


def clear() -> None:
    """Wipe the buffer (used by tests + by the admin "clear" button)."""
    with _lock:
        _buffer.clear()
