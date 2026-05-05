"""LUMO-style finite state machine for CARA.

Tracks the operational/affective state of the assistant — what is CARA
"doing right now" — so frontend bridges (Edo expression, status caption,
LED bridge) can react without polling the chat/voice/CDA flows directly.

States mirror LUMO: idle / listening / thinking / speaking / playing_media
/ sleeping / deep_sleep. Transitions emit `state_changed` on the EventBus
with both `from` and `to` so subscribers can decide what to render.

The watchdog is a long-running task that demotes the state on inactivity:
  - 5 min idle → sleeping (Edo dimmed, blue halo)
  - 30 min sleeping → deep_sleep (Edo eyes closed)
Any event that touches `mark_activity()` resets the timer.
"""

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass

import structlog

from cara.core.event_bus import EventBus, get_bus

log = structlog.get_logger(__name__)


class LumoState(str, enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    PLAYING_MEDIA = "playing_media"
    SLEEPING = "sleeping"
    DEEP_SLEEP = "deep_sleep"


# Transitions allowed from each state. Anything missing is rejected (logged
# at WARN, no exception — we don't want a stale FSM to crash chat).
_ALLOWED: dict[LumoState, set[LumoState]] = {
    LumoState.IDLE: {
        LumoState.LISTENING, LumoState.THINKING, LumoState.SPEAKING,
        LumoState.PLAYING_MEDIA, LumoState.SLEEPING,
    },
    LumoState.LISTENING: {
        LumoState.IDLE, LumoState.THINKING,
    },
    LumoState.THINKING: {
        LumoState.IDLE, LumoState.SPEAKING, LumoState.PLAYING_MEDIA,
    },
    LumoState.SPEAKING: {
        LumoState.IDLE, LumoState.LISTENING, LumoState.PLAYING_MEDIA,
    },
    LumoState.PLAYING_MEDIA: {
        LumoState.IDLE, LumoState.LISTENING, LumoState.SPEAKING,
    },
    LumoState.SLEEPING: {
        LumoState.IDLE, LumoState.LISTENING, LumoState.DEEP_SLEEP,
    },
    LumoState.DEEP_SLEEP: {
        LumoState.IDLE, LumoState.LISTENING,
    },
}


@dataclass
class WatchdogConfig:
    idle_to_sleep_seconds: float = 300.0      # 5 min
    sleep_to_deep_seconds: float = 1800.0     # 30 min
    tick_seconds: float = 5.0


class StateMachine:
    """Holds the current LumoState and broadcasts transitions on the bus.

    Thread-model: single asyncio event loop. The watchdog task and any
    `transition()` caller run in the same loop, so we don't need locking.
    """

    def __init__(self, bus: EventBus | None = None, *, watchdog: WatchdogConfig | None = None):
        self._bus = bus or get_bus()
        self._cfg = watchdog or WatchdogConfig()
        self._state: LumoState = LumoState.IDLE
        self._last_activity: float = time.monotonic()
        self._task: asyncio.Task[None] | None = None

    @property
    def state(self) -> LumoState:
        return self._state

    @property
    def last_activity(self) -> float:
        return self._last_activity

    def mark_activity(self) -> None:
        """Reset the idle timer. Called on any user-driven event."""
        self._last_activity = time.monotonic()

    def transition(self, target: LumoState) -> bool:
        """Move to `target` if the transition is allowed.

        Returns True on success, False if rejected (then the state is
        unchanged). Always emits `state_changed` on success.
        """
        if target == self._state:
            return True
        allowed = _ALLOWED.get(self._state, set())
        if target not in allowed:
            log.warning(
                "fsm.invalid_transition",
                from_=self._state.value, to=target.value,
            )
            return False
        previous = self._state
        self._state = target
        self.mark_activity()
        self._bus.emit(
            "state_changed",
            {"from": previous.value, "to": target.value},
        )
        log.info("fsm.transition", from_=previous.value, to=target.value)
        return True

    async def watchdog(self) -> None:
        """Long-running task: idle → sleeping → deep_sleep on inactivity.

        Cancellable via task.cancel(); exits cleanly on CancelledError.
        """
        while True:
            try:
                await asyncio.sleep(self._cfg.tick_seconds)
            except asyncio.CancelledError:
                return
            inactive = time.monotonic() - self._last_activity
            if self._state == LumoState.IDLE and inactive >= self._cfg.idle_to_sleep_seconds:
                self.transition(LumoState.SLEEPING)
            elif (
                self._state == LumoState.SLEEPING
                and inactive >= self._cfg.idle_to_sleep_seconds + self._cfg.sleep_to_deep_seconds
            ):
                self.transition(LumoState.DEEP_SLEEP)

    def start_watchdog(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.watchdog())

    async def stop_watchdog(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


_sm: StateMachine | None = None


def get_state_machine() -> StateMachine:
    """Return the process-global StateMachine, creating it if needed."""
    global _sm
    if _sm is None:
        _sm = StateMachine()
    return _sm


def reset_state_machine() -> None:
    """For tests — drop the singleton."""
    global _sm
    _sm = None
