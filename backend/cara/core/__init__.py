"""CARA core: event bus, state machine, watchdog.

LUMO-inspired pub/sub substrate that lets voice loop, CDA, agent loop
and (future) hardware controllers communicate without direct coupling.
"""

from cara.core.event_bus import EventBus, get_bus
from cara.core.state_machine import StateMachine, LumoState, get_state_machine

__all__ = ["EventBus", "get_bus", "StateMachine", "LumoState", "get_state_machine"]
