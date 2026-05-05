"""Skill plan executor.

Runs a deterministic linear pipeline of primitive calls. No loops, no
branching, no eval. Each step's output becomes available to later steps as
`{step_id.field}` in args; user-supplied slots are referenced as `{slot_name}`.

Failure mode: an exception in any step aborts the run and propagates a
`SkillExecutionError` with the step id + cause. The chat endpoint decides
how to surface this (fallback_response, ask_user, etc.).
"""

from __future__ import annotations

import re
import time
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.skill import Skill
from cara.skills.registry import get_primitive

log = structlog.get_logger(__name__)


class SkillExecutionError(RuntimeError):
    def __init__(self, step_id: str, cause: Exception) -> None:
        self.step_id = step_id
        self.cause = cause
        super().__init__(f"step {step_id!r} failed: {cause}")


# Matches {slot_name} or {step_id.field} or nested {step_id.field.subfield}.
_REF_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def _resolve_value(value: Any, context: dict[str, Any]) -> Any:
    """Walk strings/lists/dicts and substitute `{ref}` with values from
    `context`. Non-string leaves are returned as-is. Substitution preserves
    type when the entire string IS a single reference (e.g. `{extract.items}`
    returning the actual list, not its repr)."""
    if isinstance(value, str):
        # Whole-string single reference → preserve type
        m = _REF_RE.fullmatch(value)
        if m:
            return _lookup(m.group(1), context)
        # Otherwise interpolate as string
        return _REF_RE.sub(lambda mm: str(_lookup(mm.group(1), context, default="")), value)
    if isinstance(value, list):
        return [_resolve_value(v, context) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_value(v, context) for k, v in value.items()}
    return value


def _lookup(path: str, context: dict[str, Any], default: Any = None) -> Any:
    parts = path.split(".")
    cur: Any = context
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur


async def run(
    session: AsyncSession,
    *,
    skill: Skill,
    user_id: int,
    slots: dict[str, Any],
) -> dict[str, Any]:
    """Execute `skill.plan` in order. Returns the final context (slots + each
    step's output keyed by step id), so the response_template can interpolate."""
    context: dict[str, Any] = dict(slots)
    plan = skill.plan or {}
    steps = plan.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise SkillExecutionError("(plan)", ValueError("plan has no steps"))

    for step in steps:
        step_id = step.get("id")
        tool_name = step.get("tool")
        raw_args = step.get("args") or {}
        if not step_id or not tool_name:
            raise SkillExecutionError(
                "(plan)", ValueError(f"malformed step: {step!r}")
            )
        spec = get_primitive(tool_name)
        if spec is None:
            raise SkillExecutionError(
                step_id, ValueError(f"unknown primitive {tool_name!r}")
            )
        # Resolve {slot} and {prev_step.field} in args
        resolved = _resolve_value(raw_args, context)
        if not isinstance(resolved, dict):
            raise SkillExecutionError(
                step_id, ValueError(f"args must resolve to dict, got {type(resolved)}")
            )
        # Inject session/user_id as positional first args if the primitive needs them
        kwargs = dict(resolved)
        positional: list[Any] = []
        if spec.needs_session:
            positional.append(session)
        if spec.needs_user_id:
            positional.append(user_id)
        log.info("skill.step.start", skill=skill.name, step=step_id, tool=tool_name)
        t0 = time.perf_counter()
        try:
            output = await spec.fn(*positional, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "skill.step.failed", skill=skill.name, step=step_id,
                tool=tool_name, error=str(exc),
            )
            raise SkillExecutionError(step_id, exc) from exc
        if not isinstance(output, dict):
            output = {"value": output}
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "skill.step.done", skill=skill.name, step=step_id, tool=tool_name,
            elapsed_ms=elapsed_ms, output_keys=list(output.keys()),
        )
        context[step_id] = output
    return context


def render_response(skill: Skill, context: dict[str, Any]) -> str:
    """Apply the skill's response_template against the final execution
    context. Falls back to a generic confirmation if no template."""
    tpl = skill.response_template or "Fatto."
    return _resolve_value(tpl, context)  # type: ignore[return-value]


def render_fallback(skill: Skill, context: dict[str, Any], error: str) -> str:
    """Same idea for fallback_response (when execution failed mid-plan)."""
    tpl = skill.fallback_response or f"Mi spiace, qualcosa è andato storto: {error}"
    rendered = _resolve_value(tpl, context)
    if isinstance(rendered, str):
        return rendered
    return str(rendered)
