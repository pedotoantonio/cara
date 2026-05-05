"""In-process async pub/sub bus.

Pattern adapted from LUMO. Used to decouple components: the voice loop,
CDA orchestrator, chat agent loop and (future) wake word / face / LED
controllers all emit and listen here.

Design notes:
- Single global instance per process via `get_bus()`. The FastAPI lifespan
  in `main.py` creates it once.
- Handlers may be sync or async. Sync handlers run inline; async handlers
  are scheduled on the running loop.
- A handler crash is logged but never propagates to the emitter — events
  are best-effort, not transactional.
- Every emit is also written to `event_log.record(...)` so the existing
  diagnostics ring buffer surfaces bus activity for free.
- Wildcard `"*"` subscriber receives every event (used by the SSE
  endpoint to stream all state changes to the frontend).
"""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from typing import Any, Awaitable, Callable, Union

import structlog

from cara.services import event_log

log = structlog.get_logger(__name__)

Handler = Callable[[dict[str, Any]], Union[None, Awaitable[None]]]


class EventBus:
    """Async pub/sub bus with sync+async handler support."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, event: str, handler: Handler) -> Handler:
        """Subscribe `handler` to `event`. Returns the handler so it can be
        used as a decorator. Use `event="*"` to receive everything."""
        self._handlers[event].append(handler)
        return handler

    def off(self, event: str, handler: Handler) -> None:
        """Unsubscribe a previously-registered handler. Silent if absent."""
        try:
            self._handlers[event].remove(handler)
        except (KeyError, ValueError):
            pass

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        """Fire `event` with `payload` to all subscribers + the wildcard.

        Sync handlers run immediately in this stack frame. Async handlers
        are scheduled as tasks on the current loop. Errors are caught and
        logged.
        """
        data = payload or {}
        # Mirror to the diagnostics ring buffer so existing admin tools see
        # bus activity without any additional integration.
        try:
            event_log.record(f"bus.{event}", **data)
        except Exception:  # noqa: BLE001
            pass  # event_log failures must not block emit

        for key in (event, "*"):
            for handler in list(self._handlers.get(key, [])):
                self._dispatch(handler, event, data)

    def _dispatch(self, handler: Handler, event: str, data: dict[str, Any]) -> None:
        try:
            result = handler(data)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "bus.handler_failed",
                event=event,
                handler=getattr(handler, "__qualname__", repr(handler)),
                error=str(exc),
            )
            return
        if inspect.isawaitable(result):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop — synchronous emit() outside async context.
                # Fire-and-forget: run the coroutine to completion.
                try:
                    asyncio.run(result)  # type: ignore[arg-type]
                except Exception as exc:  # noqa: BLE001
                    log.warning("bus.async_handler_no_loop_failed", error=str(exc))
                return
            loop.create_task(self._await_safely(result, event, handler))

    @staticmethod
    async def _await_safely(coro: Awaitable[None], event: str, handler: Handler) -> None:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "bus.async_handler_failed",
                event=event,
                handler=getattr(handler, "__qualname__", repr(handler)),
                error=str(exc),
            )


_bus: EventBus | None = None


def get_bus() -> EventBus:
    """Return the process-global EventBus, creating it if needed."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_bus() -> None:
    """For tests only — drop all subscribers and start fresh."""
    global _bus
    _bus = None
