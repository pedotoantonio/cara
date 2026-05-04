"""Capability registry: the closed set of primitives a skill plan can call.

Primitives are declared via `@primitive(...)` decorator on async functions.
The decorator records metadata (name, args/returns schemas, description) used
both at runtime (executor type-checks args before calling) and at design-time
(passed to the Skill Author LLM as the menu of allowed tools).

Importing `cara.skills.primitives` is what actually registers the built-ins
— the decorator alone has no side-effect until the module is imported.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PrimitiveSpec:
    name: str
    description: str
    args_schema: dict[str, str]      # arg_name -> "string" | "int" | "bool" | "list[str]"
    returns_schema: dict[str, str]   # field_name -> type
    fn: Callable[..., Awaitable[dict[str, Any]]]
    needs_session: bool = False
    needs_user_id: bool = False


_PRIMITIVES: dict[str, PrimitiveSpec] = {}


def primitive(
    *,
    name: str,
    description: str,
    args_schema: dict[str, str],
    returns_schema: dict[str, str],
    needs_session: bool = False,
    needs_user_id: bool = False,
) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[dict[str, Any]]]]:
    """Decorator to register an async function as a skill primitive.

    The wrapped function MUST be async and MUST return a `dict` (the keys of
    which form the output context referenced as `{step_id.field}` by later
    steps). `needs_session=True` injects the active AsyncSession as first
    arg; `needs_user_id=True` injects the user id right after."""

    def deco(fn: Callable[..., Awaitable[dict[str, Any]]]):
        if name in _PRIMITIVES:
            raise ValueError(f"primitive {name!r} already registered")
        _PRIMITIVES[name] = PrimitiveSpec(
            name=name,
            description=description,
            args_schema=args_schema,
            returns_schema=returns_schema,
            fn=fn,
            needs_session=needs_session,
            needs_user_id=needs_user_id,
        )
        return fn

    return deco


def get_primitive(name: str) -> PrimitiveSpec | None:
    return _PRIMITIVES.get(name)


def list_primitives() -> list[PrimitiveSpec]:
    """Stable-ordered list of all registered primitives, for the LLM menu."""
    return sorted(_PRIMITIVES.values(), key=lambda p: p.name)
