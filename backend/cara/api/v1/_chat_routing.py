"""Routing handlers extracted from `chat.py` (Step 0.2 phase C).

The three deterministic routing tiers — skill dispatcher (Tier-0.4),
recipe chain (Tier-0.5 legacy), intent router (Tier-1) — used to live
inline as 165 lines of if/elif inside `chat()`. This module pulls each
tier into a self-contained `try_*` async function that:

  * runs the tier's `match` / `detect_intent`
  * if hit, performs the side effects (persist message, emit bus,
    record episodic event, transition state machine)
  * builds a one-shot canned `StreamingResponse` matching the
    SSE wire format the frontend expects (meta → token → done)
  * returns it; or returns None if the tier didn't match.

`chat()` then becomes:

    for handler in (try_skill_dispatcher, try_recipe_chain, try_intent_router):
        resp = await handler(...)
        if resp is not None:
            return resp

Phase C goal achieved without rewriting the streaming SSE shape: each
tier is now testable in isolation, the orchestrator is a 3-line loop,
and the future Pipeline-based replacement (phase D) can swap the loop
for `pipeline.route(ctx)` returning the same `StreamingResponse`.

`_resolve_routed_intent` (the per-intent kind dispatcher inside the
intent_router tier) was also moved here — it's owned exclusively by
that tier and removing it from `chat.py` keeps the file focused on
the LLM streaming path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.v1._chat_prompt import runtime_context_message
from cara.api.v1._chat_sse import sse_frame as _sse
from cara.cda import CdaError, DiscoverRequest, discover as cda_discover
from cara.core import LumoState, get_bus, get_state_machine
from cara.learning import episodic
from cara.models.user import User
from cara.services import conversations as convo_svc
from cara.services import event_log, intent_router
from cara.services import recipe_chain
from cara.skills import dispatcher as skill_dispatcher
from cara.skills.executor import (
    SkillExecutionError,
    render_fallback as _skill_render_fallback,
    render_response as _skill_render_response,
    run as skill_run,
)


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Canned SSE response builder shared by all three tiers
# ---------------------------------------------------------------------------


def _build_canned_stream(
    convo_id_str: str, summary: str, routed_label: str,
) -> AsyncIterator[bytes]:
    """Async generator that yields the meta + single-token + done frames.

    All three tiers produce the same shape: one chunk of pre-computed
    text, no real streaming. The frontend treats `token_id == -1` as a
    "this is a canned reply, not a real LLM token".
    """

    async def _stream() -> AsyncIterator[bytes]:
        yield _sse("meta", {"conversation_id": convo_id_str})
        yield _sse("token", {"text": summary, "token_id": -1})
        yield _sse(
            "done",
            {
                "conversation_id": convo_id_str,
                "tokens": 0,
                "first_token_seconds": 0.0,
                "total_seconds": 0.0,
                "tokens_per_second": 0.0,
                "routed": routed_label,
            },
        )

    return _stream()


def _canned_response(
    convo_id_str: str, summary: str, routed_label: str,
) -> StreamingResponse:
    return StreamingResponse(
        _build_canned_stream(convo_id_str, summary, routed_label),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Tier-0.4 — Skill Factory dispatcher
# ---------------------------------------------------------------------------


async def try_skill_dispatcher(
    *,
    session: AsyncSession,
    user: User,
    last_user_q: str | None,
    attached_files: list,
    convo: Any,
) -> StreamingResponse | None:
    """Skill dispatcher Tier-0.4 — match against active skills in DB.

    Returns a canned `StreamingResponse` if a skill matches, else None.
    Skip if no user query OR if files are attached (those need the LLM
    to reason about specific content).
    """
    if not last_user_q or attached_files:
        return None

    skill_match = await skill_dispatcher.match(session, last_user_q)
    if skill_match is None:
        return None

    sk, slots = skill_match
    try:
        ctx = await skill_run(session, skill=sk, user_id=user.id, slots=slots)
        summary = _skill_render_response(sk, ctx)
        routed_label = f"skill:{sk.name}"
    except SkillExecutionError as exc:
        log.warning(
            "chat.skill_run_failed", skill=sk.name, step=exc.step_id,
            error=str(exc.cause),
        )
        summary = _skill_render_fallback(sk, dict(slots), str(exc.cause))
        routed_label = f"skill_fallback:{sk.name}"

    await convo_svc.add_message(
        session, conversation_id=convo.id, role="assistant", content=summary,
    )
    await session.commit()
    convo_id_str = str(convo.id)
    log.info("chat.skill_run", skill=sk.name, slots=slots, summary_len=len(summary))
    get_state_machine().mark_activity()

    await episodic.record_async(
        kind="router.skill_hit",
        user_id=user.id,
        ref_id=convo_id_str,
        outcome="ok",
        payload={
            "skill": sk.name, "slots": dict(slots),
            "summary_len": len(summary),
            "label": routed_label,
        },
    )

    return _canned_response(convo_id_str, summary, routed_label)


# ---------------------------------------------------------------------------
# Tier-0.5 — Legacy recipe → ingredients chain
# ---------------------------------------------------------------------------


async def try_recipe_chain(
    *,
    session: AsyncSession,
    user: User,
    last_user_q: str | None,
    attached_files: list,
    convo: Any,
) -> StreamingResponse | None:
    """Legacy recipe → ingredients chain (Tier-0.5).

    Kept as a fallback in case the corresponding `ricetta_to_spesa`
    skill in DB is disabled. Active skill normally pre-empts this tier
    via Tier-0.4 above.
    """
    if not last_user_q or attached_files:
        return None

    recipe_dish = recipe_chain.detect_intent(last_user_q)
    if not recipe_dish:
        return None

    try:
        summary = await recipe_chain.run(
            session, user_id=user.id, dish=recipe_dish,
        )
    except Exception as exc:  # noqa: BLE001 — surface as friendly fallback
        log.exception("chat.recipe_chain_failed", dish=recipe_dish, error=str(exc))
        summary = (
            f"Ho avuto un problema cercando la ricetta di {recipe_dish}. "
            "Riprova fra un momento."
        )

    await convo_svc.add_message(
        session, conversation_id=convo.id, role="assistant", content=summary,
    )
    await session.commit()
    convo_id_str = str(convo.id)
    log.info("chat.recipe_chain", dish=recipe_dish, summary_len=len(summary))
    get_state_machine().mark_activity()

    await episodic.record_async(
        kind="router.recipe_chain_hit",
        user_id=user.id,
        ref_id=convo_id_str,
        outcome="ok",
        payload={"dish": recipe_dish, "summary_len": len(summary)},
    )

    return _canned_response(convo_id_str, summary, "recipe_chain")


# ---------------------------------------------------------------------------
# Tier-1 — Deterministic intent router + per-kind resolver
# ---------------------------------------------------------------------------


async def _resolve_routed_intent(
    *,
    session: AsyncSession,
    user_id: int,
    routed: "intent_router.RoutedIntent",
) -> str:
    """Execute the side-effect implied by a routed intent and return the
    canned reply text. Stays small: every branch must be O(1) calls and
    return in well under a second so we keep the latency promise."""
    kind = routed.kind
    args = routed.args

    if kind == "go_sleep":
        sm = get_state_machine()
        # Allow direct idle→sleeping; from any other state, route via idle first
        # so the FSM transition table doesn't reject it.
        if sm.state != LumoState.IDLE and sm.state != LumoState.SLEEPING:
            sm.transition(LumoState.IDLE)
        sm.transition(LumoState.SLEEPING)
        return routed.canned_reply or "Buonanotte."

    if kind == "wake_up":
        sm = get_state_machine()
        if sm.state in (LumoState.SLEEPING, LumoState.DEEP_SLEEP):
            sm.transition(LumoState.IDLE)
        sm.mark_activity()
        return routed.canned_reply or "Eccomi."

    if kind == "answer_datetime":
        # Use the very same context block we'd inject into the LLM prompt.
        ctx = runtime_context_message()
        # Take the first two informational lines and stitch them into prose.
        lines = [
            ln.lstrip("- ").rstrip(".")
            for ln in ctx.splitlines()
            if ln.startswith("- Oggi") or ln.startswith("- Ora")
        ]
        if lines:
            return ". ".join(lines) + "."
        return routed.canned_reply

    if kind == "discover_audio":
        try:
            res = await cda_discover(
                session,
                DiscoverRequest(
                    user_id=user_id,
                    raw_query=args.get("query", ""),
                    content_type="audio_stream",
                ),
            )
            return f"In onda: {res.title or args.get('query', '')}."
        except CdaError as exc:
            return f"Non sono riuscita a trovare la radio: {exc}"

    if kind == "discover_article":
        try:
            res = await cda_discover(
                session,
                DiscoverRequest(
                    user_id=user_id,
                    raw_query=args.get("query", ""),
                    content_type="article",
                ),
            )
        except CdaError as exc:
            return f"Non sono riuscita a trovarlo: {exc}"
        cached = (res.metadata or {}).get("cached_answer")
        if cached and isinstance(cached, str):
            attribution = f"\n\n*(fonte: {res.source_domain})*" if res.source_domain else ""
            return cached + attribution
        # No cached answer yet — return a brief stub so the user knows we
        # found something. The agent loop normally fills this in for free,
        # but routed intents skip the LLM entirely; we accept the trade-off
        # of a thinner first answer here in exchange for sub-second latency.
        title = res.title or args.get("query", "")
        src = f" (fonte: {res.source_domain})" if res.source_domain else ""
        return f"Ho trovato: {title}{src}. Apri il link nelle scoperte per leggerlo."

    if kind == "list_tasks":
        from cara.services import tasks as task_svc
        items = await task_svc.list_tasks(session, user_id=user_id, include_done=False)
        if not items:
            return "Niente da fare al momento."
        body = "\n".join(f"• {t.title}" for t in items[:10])
        more = f"\n…(+{len(items) - 10} altre)" if len(items) > 10 else ""
        return f"Ecco le tue cose da fare:\n{body}{more}"

    if kind == "add_task":
        from cara.services import tasks as task_svc
        title = args.get("title", "").strip()
        if not title:
            return "Cosa devo aggiungere?"
        t = await task_svc.create_task(session, user_id=user_id, title=title)
        return f"Aggiunto: \"{t.title}\"."

    if kind == "add_shopping":
        from cara.services import shopping as shop_svc
        title = args.get("title", "").strip()
        if not title:
            return "Cosa devo aggiungere alla spesa?"
        s = await shop_svc.create_item(session, user_id=user_id, title=title)
        return f"Messo nella spesa: \"{s.title}\"."

    if kind == "who_is_home":
        from cara.services.family import FamilyPresenceUnavailable, people_present
        try:
            seen = await people_present(window_minutes=15)
        except FamilyPresenceUnavailable as exc:
            return f"Non riesco a controllare le telecamere: {exc}"
        except Exception as exc:  # noqa: BLE001
            log.warning("chat.routed.who_is_home_error", error=str(exc))
            return "Non riesco a controllare le telecamere in questo momento."
        if not seen:
            return "In questo momento non vedo nessuno in casa."
        names = ", ".join(p.name for p in seen)
        return f"In casa adesso: {names}."

    if kind == "get_news":
        from cara.services import news as news_svc
        cat = args.get("category", "all")
        items = await news_svc.fetch_category(cat, limit=5)
        if not items:
            return "Non ho trovato notizie al momento."
        digest = news_svc.make_digest(items[:5], category=cat)
        return digest

    return routed.canned_reply or "Fatto."


async def try_intent_router(
    *,
    session: AsyncSession,
    user: User,
    last_user_q: str | None,
    attached_files: list,
    convo: Any,
) -> StreamingResponse | None:
    """Tier-1 deterministic intent router — catches canonical commands
    before the LLM is invoked, avoiding 6-90s of token latency."""
    if not last_user_q or attached_files:
        return None

    routed = intent_router.match(last_user_q)
    if routed is None:
        return None

    import time as _t
    _t0 = _t.perf_counter()
    sm = get_state_machine()
    bus = get_bus()
    sm.transition(LumoState.THINKING)
    bus.emit(
        "chat.routed.start",
        {"user_id": user.id, "intent": routed.kind, "query": last_user_q[:80]},
    )
    canned = await _resolve_routed_intent(
        session=session, user_id=user.id, routed=routed,
    )
    elapsed_ms = int((_t.perf_counter() - _t0) * 1000)

    await convo_svc.add_message(
        session, conversation_id=convo.id, role="assistant", content=canned,
    )
    await session.commit()
    convo_id_str = str(convo.id)
    log.info(
        "chat.intent_routed",
        kind=routed.kind, args=routed.args, reply_chars=len(canned),
    )
    event_log.record(
        "intent_router.match",
        user_id=user.id,
        duration_ms=elapsed_ms,
        intent=routed.kind,
        query=last_user_q[:80],
        args=routed.args,
    )
    await episodic.record_async(
        kind="router.intent_hit",
        user_id=user.id,
        ref_id=convo_id_str,
        outcome="ok",
        duration_ms=elapsed_ms,
        payload={
            "intent": routed.kind,
            "args": routed.args,
            "query": last_user_q[:200] if last_user_q else "",
            "reply_chars": len(canned),
        },
    )
    bus.emit(
        "chat.routed.done",
        {
            "user_id": user.id,
            "intent": routed.kind,
            "duration_ms": elapsed_ms,
            "reply_chars": len(canned),
        },
    )
    sm.transition(LumoState.SPEAKING)
    sm.transition(LumoState.IDLE)

    return _canned_response(convo_id_str, canned, routed.kind)


# Ordered list of routing tiers — `chat()` walks this list in order,
# returning the first non-None response. Adding a new tier becomes
# adding one entry here + one async function above.
ROUTING_TIERS = (
    try_skill_dispatcher,
    try_recipe_chain,
    try_intent_router,
)
