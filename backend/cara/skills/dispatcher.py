"""Skill dispatcher — Tier-1 (regex match against per-skill patterns).

For each active skill, this module compiles its `slot_extraction.<slot>.pattern`
into a regex. On `match(message)`, the dispatcher tries every active skill's
patterns; the first one that matches wins. Returns `(skill, slots)` so the
chat endpoint can hand off directly to the executor.

Tier-2 (embedding-based fuzzy match) and Tier-3 (LLM classifier) are TODO.
This first slice is regex-only — same fidelity as the hand-coded
`recipe_chain.detect_intent` it replaces, but driven by data in DB instead of
Python source.

Cache: skills are loaded into memory at first call and refreshed via
`invalidate_cache()` after CRUD on the `skills` table.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.skill import Skill

log = structlog.get_logger(__name__)


_cache: list[Skill] | None = None


async def _load_active(session: AsyncSession) -> list[Skill]:
    global _cache
    if _cache is not None:
        return _cache
    rows = (
        (await session.execute(select(Skill).where(Skill.status == "active")))
        .scalars()
        .all()
    )
    _cache = list(rows)
    log.info("skill.dispatcher.cache_loaded", n=len(_cache))
    return _cache


def invalidate_cache() -> None:
    global _cache
    _cache = None


def _extract_slots(message: str, slot_extraction: dict[str, Any]) -> dict[str, str] | None:
    """Apply the skill's slot regexes to `message`. All required slots must
    match; returns a {slot_name: value} dict, or None if any slot fails.

    A slot definition has the shape:
      {"method": "regex", "pattern": "...", "group": 1, "required": true}
    The `required` defaults to True. Captured group is stripped + lowered.
    """
    out: dict[str, str] = {}
    for slot, spec in (slot_extraction or {}).items():
        if not isinstance(spec, dict):
            continue
        method = spec.get("method", "regex")
        if method != "regex":
            # Only regex method supported in this slice
            continue
        pattern = spec.get("pattern", "")
        group = int(spec.get("group", 1))
        required = bool(spec.get("required", True))
        try:
            m = re.search(pattern, message, flags=re.IGNORECASE)
        except re.error as exc:
            log.warning("skill.slot.invalid_regex", slot=slot, error=str(exc))
            return None
        if m is None:
            if required:
                return None
            continue
        try:
            value = (m.group(group) or "").strip(" .,;:")
        except IndexError:
            if required:
                return None
            continue
        if not value:
            if required:
                return None
            continue
        out[slot] = value
    return out


async def match(
    session: AsyncSession, message: str
) -> tuple[Skill, dict[str, str]] | None:
    """Try each active skill in order. Return the first match.

    Ordering: skills are returned by SQL in PK order (insertion). For better
    determinism in production, future versions should add `priority INT` or
    sort by success_rate desc — out of scope for this slice.
    """
    if not message or not message.strip():
        return None
    skills = await _load_active(session)
    for sk in skills:
        slots = _extract_slots(message, sk.slot_extraction or {})
        if slots is None:
            continue
        # If the skill has slot_extraction defined and they all matched,
        # consider it a hit. A skill with NO slots isn't really
        # disambiguated by user input — for now, those need explicit
        # intent_examples handling (TODO Tier-2 embeddings).
        if not sk.slot_extraction:
            continue
        log.info(
            "skill.dispatcher.match",
            skill=sk.name, slots=slots,
        )
        return sk, slots
    return None
