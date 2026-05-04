"""Skill Factory v0.7 — auto-skill bootstrapping.

See `/opt/cara/docs/skill-factory-extension-prompt.md` for the full design.

Public API:
- `@primitive(...)` decorator: registers a callable as a skill primitive
- `dispatcher.match(message)`: Tier-1 regex match → (Skill, slots) | None
- `executor.run(...)`: deterministic execution of a skill plan
"""

from cara.skills.registry import (
    PrimitiveSpec,
    get_primitive,
    list_primitives,
    primitive,
)

__all__ = [
    "PrimitiveSpec",
    "get_primitive",
    "list_primitives",
    "primitive",
]
