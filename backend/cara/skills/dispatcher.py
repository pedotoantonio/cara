"""Skill dispatcher — Tier-1 regex / Tier-2 cosine / Tier-3 LLM classifier.

Three tiers, evaluated in order on every chat message until one matches:

  Tier-1 — `slot_extraction.<slot>.pattern` regex match against `message`.
           Free, deterministic, fastest. Always on. Same fidelity as the
           hand-coded `recipe_chain.detect_intent` it replaces, but
           data-driven from DB instead of Python source.

  Tier-2 — cosine similarity between an embedding of the user message
           and the embeddings of `intent_examples` for each active skill.
           ~50 ms per attempt thanks to the cached index. Toggled by
           `skill_dispatcher_tier2_enabled`. Threshold tunable via
           `skill_dispatcher_tier2_threshold` (default 0.65).

  Tier-3 — local 1.5B LLM picks the skill with a structured prompt
           ("from this list, which best matches? answer with a number,
           or 0 if none"). Roughly 500 ms - 2 s on the NPU; OFF by
           default. Toggled by `skill_dispatcher_tier3_enabled`. Use
           when you want CARA to learn aggressively from chat misses.

Slot extraction runs AFTER any tier identifies a skill — Tier-2/3 mean
"the user's intent matches this skill", but the executor still needs the
slot values. Failures degrade gracefully: the executor's
`fallback_response` surfaces the issue, and the chat layer falls
through to the LLM as if no skill had matched.

Cache: skills are loaded into memory at first call. Tier-2 also caches
the per-skill embedding matrix. Both are invalidated by
`invalidate_cache()` after CRUD on the `skills` table.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.skill import Skill

log = structlog.get_logger(__name__)


# Tier-1 cache: list of active skills (regex/slot setup is per-call).
_cache: list[Skill] | None = None

# Tier-2 cache: skill_id -> (skill, list of intent embedding vectors).
_tier2_index: dict[str, tuple[Skill, list[list[float]]]] | None = None

# Lock to serialize index rebuilds (encoding is CPU-bound, async IO).
_tier2_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


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
    """Drop both Tier-1 and Tier-2 caches. Called on any skill CRUD."""
    global _cache, _tier2_index
    _cache = None
    _tier2_index = None


def _extract_slots(
    message: str, slot_extraction: dict[str, Any]
) -> dict[str, str] | None:
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


# ---------------------------------------------------------------------------
# Tier-1: regex
# ---------------------------------------------------------------------------


async def _match_tier1(
    session: AsyncSession, message: str
) -> tuple[Skill, dict[str, str]] | None:
    skills = await _load_active(session)
    for sk in skills:
        if not sk.slot_extraction:
            # Skills without slot patterns can only be reached via Tier-2/3.
            continue
        slots = _extract_slots(message, sk.slot_extraction or {})
        if slots is None:
            continue
        log.info(
            "skill.dispatcher.tier1.match", skill=sk.name, slots=slots,
        )
        return sk, slots
    return None


# ---------------------------------------------------------------------------
# Tier-2: cosine similarity over intent_examples
# ---------------------------------------------------------------------------


async def _build_tier2_index(
    session: AsyncSession, embedder: Any,
) -> dict[str, tuple[Skill, list[list[float]]]]:
    """Encode every active skill's intent_examples once, keep in memory.

    Skills with empty intent_examples are absent from the index — they
    are unreachable via Tier-2 (Tier-1 regex or Tier-3 LLM only).
    """
    skills = await _load_active(session)
    index: dict[str, tuple[Skill, list[list[float]]]] = {}
    for sk in skills:
        examples = [s for s in (sk.intent_examples or []) if isinstance(s, str) and s.strip()]
        if not examples:
            continue
        try:
            results = await embedder.encode_many(examples)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "skill.dispatcher.tier2.encode_failed",
                skill=sk.name, error=str(exc),
            )
            continue
        vectors = [r.vector for r in results if r.vector]
        if vectors:
            index[str(sk.id)] = (sk, vectors)
    log.info("skill.dispatcher.tier2.index_built", n_skills=len(index))
    return index


async def _ensure_tier2_index(session: AsyncSession, embedder: Any) -> None:
    global _tier2_index
    if _tier2_index is not None:
        return
    async with _tier2_lock:
        if _tier2_index is not None:
            return
        _tier2_index = await _build_tier2_index(session, embedder)


def _cosine(a: list[float], b: list[float]) -> float:
    # Both inputs are L2-normalised by the embedder, so dot-product == cosine.
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    s = 0.0
    for i in range(n):
        s += a[i] * b[i]
    if s > 1.0:
        return 1.0
    if s < -1.0:
        return -1.0
    return s


async def _match_tier2(
    session: AsyncSession,
    message: str,
    embedder: Any,
    threshold: float,
) -> tuple[Skill, dict[str, str], float] | None:
    await _ensure_tier2_index(session, embedder)
    if not _tier2_index:
        return None
    try:
        msg = await embedder.encode(message)
    except Exception as exc:  # noqa: BLE001
        log.debug("skill.dispatcher.tier2.encode_failed", error=str(exc))
        return None
    msg_vec = msg.vector
    best_skill: Skill | None = None
    best_score = 0.0
    for _sid, (sk, vecs) in _tier2_index.items():
        for v in vecs:
            s = _cosine(msg_vec, v)
            if s > best_score:
                best_score = s
                best_skill = sk
    if best_skill is None or best_score < threshold:
        return None
    slots = _extract_slots(message, best_skill.slot_extraction or {}) or {}
    log.info(
        "skill.dispatcher.tier2.match",
        skill=best_skill.name, score=round(best_score, 3), slots=slots,
    )
    return best_skill, slots, best_score


# ---------------------------------------------------------------------------
# Tier-3: LLM classifier
# ---------------------------------------------------------------------------


# A callable that takes (prompt, max_new_tokens) and returns the model
# response as a string. Decoupled from the LLMService class so tests can
# inject a fake.
LlmCallable = Callable[[str, int], Awaitable[str]]


def _make_classifier_prompt(skills: list[Skill], message: str) -> str:
    catalog_lines = []
    for i, sk in enumerate(skills, start=1):
        # Keep each line short — lower-precision LLM stays in budget.
        desc = (sk.description or "").splitlines()[0][:120]
        catalog_lines.append(f"{i}. {sk.name}: {desc}")
    return (
        "Hai questi skill disponibili:\n\n"
        + "\n".join(catalog_lines)
        + f"\n\nUtente ha detto: \"{message.strip()}\"\n\n"
        "Rispondi SOLO con il numero della skill che meglio corrisponde, "
        "oppure 0 se nessuna è adatta. Solo il numero, niente altro."
    )


_CLASSIFIER_NUMBER_RE = re.compile(r"\b(\d+)\b")


async def _match_tier3_llm(
    session: AsyncSession,
    message: str,
    llm_call: LlmCallable,
) -> tuple[Skill, dict[str, str]] | None:
    skills = await _load_active(session)
    if not skills:
        return None
    prompt = _make_classifier_prompt(skills, message)
    try:
        response = await llm_call(prompt, 6)
    except Exception as exc:  # noqa: BLE001
        log.warning("skill.dispatcher.tier3.llm_failed", error=str(exc))
        return None
    m = _CLASSIFIER_NUMBER_RE.search(response or "")
    if not m:
        return None
    try:
        idx = int(m.group(1))
    except ValueError:
        return None
    if idx <= 0 or idx > len(skills):
        return None
    sk = skills[idx - 1]
    slots = _extract_slots(message, sk.slot_extraction or {}) or {}
    log.info(
        "skill.dispatcher.tier3.match",
        skill=sk.name, raw=response[:32], slots=slots,
    )
    return sk, slots


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def match_with_tier(
    session: AsyncSession,
    message: str,
    *,
    embedder: Any | None = None,
    llm_call: LlmCallable | None = None,
    tier2_enabled: bool = True,
    tier3_enabled: bool = False,
    tier2_threshold: float = 0.65,
) -> tuple[Skill, dict[str, str], str, float] | None:
    """Try Tier-1 → Tier-2 → Tier-3.

    Returns `(skill, slots, tier_name, confidence)` on hit, else None.
    `tier_name` ∈ {"tier1", "tier2", "tier3"}; `confidence` is 1.0 for
    tier1/tier3 and the cosine score for tier2.
    """
    if not message or not message.strip():
        return None

    hit1 = await _match_tier1(session, message)
    if hit1 is not None:
        sk, slots = hit1
        return sk, slots, "tier1", 1.0

    if tier2_enabled and embedder is not None:
        hit2 = await _match_tier2(session, message, embedder, tier2_threshold)
        if hit2 is not None:
            sk, slots, score = hit2
            return sk, slots, "tier2", score

    if tier3_enabled and llm_call is not None:
        hit3 = await _match_tier3_llm(session, message, llm_call)
        if hit3 is not None:
            sk, slots = hit3
            return sk, slots, "tier3", 1.0

    return None


async def match(
    session: AsyncSession, message: str
) -> tuple[Skill, dict[str, str]] | None:
    """Backward-compatible signature: Tier-1 only by default.

    To enable Tier-2/3 from a caller, use `match_with_tier()` and pass
    the embedder + llm_call. The router-level glue in `_chat_routing`
    is the canonical caller.
    """
    hit = await match_with_tier(session, message)
    if hit is None:
        return None
    sk, slots, _tier, _conf = hit
    return sk, slots
