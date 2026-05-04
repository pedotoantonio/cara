"""Routing pipeline — staged dispatch from user message to response.

Today (`chat.py` 1151 lines), routing is implicit: a chain of `if` checks
in the chat handler, with cache, intent regex, recipe chain, skill
dispatcher, tool calling and LLM fallback all woven inline. Adding a new
fast-path means surgery in the hot path. Removing one is even harder.

The pipeline turns that into an explicit list of `Stage`s. Each stage
returns Hit (handled) or Miss (with a reason). The dispatcher walks the
list, logs every hop in `episodic`, and stops at the first Hit. New
fast-paths become new stages — wired without touching the chat handler.

This module ships the *infrastructure*: protocol, dispatcher, dataclasses,
two trivial stages for testing (`AlwaysMissStage`, `AlwaysHitStage`).
The real wiring of cache / intent / skills / LLM stages onto the running
chat hot path comes after `chat.py` is refactored (Step 0.2, blocked on
Antonio's Step 66 commit).
"""

from cara.router.pipeline import (
    AlwaysHitStage,
    AlwaysMissStage,
    Hit,
    Miss,
    Pipeline,
    RouteContext,
    Stage,
    StageResult,
)

__all__ = [
    "AlwaysHitStage",
    "AlwaysMissStage",
    "Hit",
    "Miss",
    "Pipeline",
    "RouteContext",
    "Stage",
    "StageResult",
]
