"""Proactivity engine — CARA suggests, never insists.

CARA earns its place in the family only if she's *attente, mai
invadente*. The proactivity engine is what lets her notice things
worth surfacing — *"Marco di solito torna alle 19 ed è già le 20:30,
gli scrivo?"*, *"Domani pioverà alle 16, prendi l'ombrello"* — without
becoming the assistant nobody can tolerate.

Three principles, encoded in the engine:

  1. **Proposing, not deciding.** Every rule produces a `Suggestion`,
     never a side effect. The user sees a card, can dismiss with one
     tap, can act on it with one tap. CARA never sends a message,
     turns off a light, or schedules a task on her own.

  2. **Cooldown by default.** A rule that just fired won't fire again
     for `cooldown_hours` (default 24). Avoids the "Alexa screams
     every five minutes about the dishwasher" failure mode.

  3. **Silent hours.** Configurable window (default 22:00-07:00)
     during which only `urgent` priority suggestions surface — most
     family households want CARA to shut up at night.

Rules register via `@rule(...)` decorator. The engine walks them on
each tick (default every 5 minutes), filters by silent hours +
cooldown + per-user opt-in, and persists each surviving suggestion
into the `proactivity_queue` table for the UI to consume.

This module ships the engine + the registry. Concrete rules live in
`cara.services.proactivity.rules` (Step 8.7).
"""

from cara.services.proactivity.engine import (
    Priority,
    ProactivityEngine,
    RuleContext,
    Suggestion,
    rule,
    register_rule,
    registry,
)

__all__ = [
    "Priority",
    "ProactivityEngine",
    "RuleContext",
    "Suggestion",
    "register_rule",
    "registry",
    "rule",
]
