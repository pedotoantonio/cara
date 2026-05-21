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
from cara.services import admin_settings
from cara.services import conversations as convo_svc
from cara.services import event_log, intent_router
from cara.services import quick_calc
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
# Tier-0.35 — Smart home (HA REST adapter via SmartHomeNLU)
# ---------------------------------------------------------------------------

# Cheap regex prefilter — if the utterance doesn't open with a smart-home
# verb we don't even build the NLU. Saves the per-turn HA roundtrip on
# ~99% of chat messages.
import re as _re

_SMARTHOME_PREFILTER = _re.compile(
    r"\b(?:accendi|spegni|attiv[ai]|disattiv[ai]|"
    r"apri|chiudi|imposta|metti|"
    r"blocc[ai]|sblocc[ai])\b",
    _re.IGNORECASE,
)


async def try_smarthome(
    *,
    session: AsyncSession,
    user: User,
    last_user_q: str | None,
    attached_files: list,
    convo: Any,
) -> StreamingResponse | None:
    """Smart-home tier: when the utterance starts with a control verb,
    resolve via the SmartHomeNLU + HA adapter and call the service.

    Skipped when:
      - the cheap prefilter doesn't match (no verb)
      - smarthome.enabled is False (no HA configured)
      - the NLU returns needs_clarification (we let the LLM rephrase
        as a question rather than guess a wrong device)
    """
    if not last_user_q or attached_files:
        return None
    if not _SMARTHOME_PREFILTER.search(last_user_q):
        return None

    # Lazy imports — keep the cold startup of the chat module independent
    # of the smart-home feature.
    from cara.api.v1.smarthome import _resolve_adapter
    from cara.smarthome.nlu import (
        Action,
        SmartHomeNLU,
        aliases_from_entities,
    )
    from cara.models.device_permission import (
        ACTION_CONTROL, ACTION_LOCK,
        PERM_DENY, PERM_ASK,
    )
    from cara.services.smarthome_permissions import check_permission

    try:
        adapter = await _resolve_adapter(session)
    except Exception as exc:  # noqa: BLE001
        log.warning("chat.smarthome.adapter_failed", error=str(exc))
        return None
    if adapter is None:
        return None

    try:
        entities = await adapter.list_entities()
    except Exception as exc:  # noqa: BLE001
        log.warning("chat.smarthome.list_entities_failed", error=str(exc))
        return None

    nlu = SmartHomeNLU(aliases_from_entities(entities))
    res = await nlu.resolve(last_user_q)

    if not res.matched_intent or res.needs_clarification or res.chosen() is None:
        # Either no smart-home phrase or we'd guess wrong — fall through
        # to the LLM (which can ask "quale luce?").
        return None

    target = res.chosen()
    assert target is not None  # narrowed above

    # Map Action → HA (domain, service)
    domain, _, _ = target.entity_id.partition(":")  # canonical "homeassistant:light.salotto"
    if "." in target.entity_id:
        ha_entity = target.entity_id.split(":", 1)[1]
        ha_domain = ha_entity.split(".", 1)[0]
    else:
        ha_entity = target.entity_id
        ha_domain = "homeassistant"

    SERVICE_MAP = {
        Action.TURN_ON:  ("turn_on",  ACTION_CONTROL),
        Action.TURN_OFF: ("turn_off", ACTION_CONTROL),
        Action.TOGGLE:   ("toggle",   ACTION_CONTROL),
        Action.OPEN:     ("open_cover" if ha_domain == "cover" else "turn_on", ACTION_CONTROL),
        Action.CLOSE:    ("close_cover" if ha_domain == "cover" else "turn_off", ACTION_CONTROL),
        Action.LOCK:     ("lock",   ACTION_LOCK),
        Action.UNLOCK:   ("unlock", ACTION_LOCK),
    }
    if res.action not in SERVICE_MAP:
        # SET_VALUE / QUERY / SCENE_ACTIVATE — let the LLM handle for now
        # (they need extra param munging that's out of scope here).
        return None

    service, action_axis = SERVICE_MAP[res.action]

    perm = await check_permission(
        session,
        user_id=user.id,
        user_role=user.role or "guest",
        entity_id=target.entity_id,
        action=action_axis,
    )
    if perm.decision == PERM_DENY:
        canned = f"Mi spiace, non sei autorizzato a controllare {target.alias}."
    elif perm.decision == PERM_ASK:
        # We don't have a confirmation UI in the chat stream; ask the user
        # to repeat with explicit "sì conferma".
        canned = (
            f"Per {target.alias} serve conferma. "
            f"Rispondi \"conferma {target.alias}\" se vuoi davvero."
        )
    else:
        try:
            result = await adapter.call_service(
                ha_domain, service, ha_entity, params={},
            )
            ok = bool(result.get("ok"))
        except Exception as exc:  # noqa: BLE001
            log.warning("chat.smarthome.call_failed", error=str(exc), entity=ha_entity)
            ok = False

        if ok:
            verb_past = {
                Action.TURN_ON: "Acceso", Action.TURN_OFF: "Spento",
                Action.TOGGLE: "Cambiato", Action.OPEN: "Aperto",
                Action.CLOSE: "Chiuso",   Action.LOCK: "Bloccato",
                Action.UNLOCK: "Sbloccato",
            }.get(res.action, "Fatto")
            canned = f"{verb_past}: {target.alias}."
        else:
            canned = f"Non sono riuscita ad agire su {target.alias}."

    await convo_svc.add_message(
        session, conversation_id=convo.id, role="assistant", content=canned,
    )
    await session.commit()
    convo_id_str = str(convo.id)
    log.info(
        "chat.smarthome.executed",
        action=res.action.value,
        entity=ha_entity,
        ok=("non sono riuscita" not in canned.lower()),
    )

    await episodic.record_async(
        kind="router.smarthome_hit",
        user_id=user.id,
        ref_id=convo_id_str,
        outcome="ok",
        payload={
            "action": res.action.value,
            "entity": ha_entity,
            "alias": target.alias,
        },
    )

    return _canned_response(convo_id_str, canned, f"smarthome:{res.action.value}")


# ---------------------------------------------------------------------------
# Tier-0.3 — Quick deterministic calc (math / time / date)
# ---------------------------------------------------------------------------


async def try_quick_calc(
    *,
    session: AsyncSession,
    user: User,
    last_user_q: str | None,
    attached_files: list,
    convo: Any,
) -> StreamingResponse | None:
    """Intercept arithmetic, time and date queries before the LLM.

    The 1.5B Qwen frequently invents numbers (`6 per 7 = 21`) and gets
    confused on date offsets. Routing those to a Python evaluator costs
    nothing and removes the most embarrassing class of errors. Skips
    when files are attached (the user wants reasoning over content).
    """
    if not last_user_q or attached_files:
        return None

    answer = quick_calc.try_calc(last_user_q)
    if answer is None:
        return None

    await convo_svc.add_message(
        session, conversation_id=convo.id, role="assistant", content=answer,
    )
    await session.commit()
    convo_id_str = str(convo.id)
    log.info("chat.quick_calc.hit", q=last_user_q[:80], answer=answer)
    get_state_machine().mark_activity()

    await episodic.record_async(
        kind="router.quick_calc_hit",
        user_id=user.id,
        ref_id=convo_id_str,
        outcome="ok",
        payload={"q": last_user_q[:160], "answer": answer},
    )

    return _canned_response(convo_id_str, answer, "quick_calc")


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

    # Tier configuration is read from admin_settings live so the admin
    # can flip cosine/LLM matching on or off without redeploying.
    settings = await admin_settings.get_all(session)
    tier2_on = bool(settings.get("skill_dispatcher_tier2_enabled", True))
    tier3_on = bool(settings.get("skill_dispatcher_tier3_enabled", False))
    tier2_threshold = float(settings.get("skill_dispatcher_tier2_threshold", 0.65))

    embedder = None
    if tier2_on:
        try:
            from cara.ai.embeddings import EmbeddingService
            embedder = EmbeddingService()
        except Exception as exc:  # noqa: BLE001
            log.debug("chat.skill_dispatcher.embedder_unavailable", error=str(exc))

    llm_call = None
    if tier3_on:
        try:
            from cara.ai.llm import get_llm_service
            svc = get_llm_service()

            async def _llm_call(prompt: str, max_new_tokens: int) -> str:
                # Wrap the streaming generate as a single-shot collector.
                chunks: list[str] = []
                async for tok in svc.generate(
                    prompt, max_new_tokens=max_new_tokens, temperature=0.1,
                ):
                    chunks.append(tok.text)
                return "".join(chunks)
            llm_call = _llm_call
        except Exception as exc:  # noqa: BLE001
            log.debug("chat.skill_dispatcher.llm_unavailable", error=str(exc))

    matched = await skill_dispatcher.match_with_tier(
        session, last_user_q,
        embedder=embedder, llm_call=llm_call,
        tier2_enabled=bool(embedder), tier3_enabled=bool(llm_call),
        tier2_threshold=tier2_threshold,
    )
    if matched is None:
        return None

    sk, slots, tier_name, confidence = matched
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
            "tier": tier_name,
            "confidence": round(confidence, 3),
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


# Capability self-description. CARA cites this verbatim when asked
# "cosa sai fare". Updating capabilities? Edit here AND keep the system
# prompt in sync (cara.config.settings.llm_system_prompt).
_CAPABILITIES_BLURB = (
    "Posso aiutarti con queste cose:\n"
    "• Task: aggiungere, completare, duplicare, cancellare, vedere la lista, filtrare per oggi.\n"
    "• Lista della spesa: aggiungere articoli, segnarli come presi, cancellarli, leggere la lista.\n"
    "• Note: salvare un appunto, leggerle, cancellarle.\n"
    "• Appuntamenti: vedere quelli di oggi, di domani o di tutta la settimana.\n"
    "• News: ultime notizie per categoria.\n"
    "• Radio: avviare e fermare stazioni.\n"
    "• Famiglia: dirti chi è in casa adesso.\n"
    "• Ricerche su internet: meteo, definizioni, fatti.\n"
    "• Domande di matematica e date senza errori.\n"
    "Puoi parlare o scrivere — funziona allo stesso modo."
)


def _norm_for_match(s: str) -> str:
    """Lowercase + strip diacritics + drop leading Italian articles +
    collapse whitespace, used for fuzzy title matching (so "il pane"
    matches "pane", "caffè" matches "caffe")."""
    import re
    import unicodedata
    s = (s or "").lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s).strip()
    # Strip leading Italian definite/indefinite articles + a small set of
    # demonstratives. Keeps the body intact ("il pane bianco" → "pane bianco").
    s = re.sub(
        r"^(?:il|lo|la|i|gli|le|un|uno|una|un['\s]|dei|degli|delle|del|dello|della|"
        r"questo|questa|questi|queste|quel|quella|quei|quelle)\s+",
        "",
        s,
    )
    return s.strip()


async def _find_task_by_title(session: AsyncSession, *, user_id: int, title: str):
    """Return the best-matching open task (or done if no open) by title.

    Strategy: exact match (case- and accent-insensitive) wins; otherwise
    the task whose title contains the query as a substring. Open tasks
    preferred over done. Returns None if no plausible match.
    """
    from cara.services import tasks as task_svc
    rows = await task_svc.list_tasks(session, user_id=user_id, include_done=True)
    needle = _norm_for_match(title)
    if not needle:
        return None
    open_rows = [t for t in rows if not t.done]
    done_rows = [t for t in rows if t.done]
    for bucket in (open_rows, done_rows):
        for t in bucket:
            if _norm_for_match(t.title) == needle:
                return t
        for t in bucket:
            if needle in _norm_for_match(t.title):
                return t
    return None


async def _find_shopping_by_title(session: AsyncSession, *, user_id: int, title: str):
    from cara.services import shopping as shop_svc
    rows = await shop_svc.list_items(session, user_id=user_id)
    needle = _norm_for_match(title)
    if not needle:
        return None
    not_bought = [s for s in rows if not s.bought]
    bought = [s for s in rows if s.bought]
    for bucket in (not_bought, bought):
        for s in bucket:
            if _norm_for_match(s.title) == needle:
                return s
        for s in bucket:
            if needle in _norm_for_match(s.title):
                return s
    return None


async def _find_note_by_title(session: AsyncSession, *, user_id: int, title: str):
    from cara.services import notes as notes_svc
    rows = await notes_svc.list_notes(session, user_id=user_id)
    needle = _norm_for_match(title)
    if not needle:
        return None
    for n in rows:
        if _norm_for_match(n.title or "") == needle:
            return n
    for n in rows:
        if needle in _norm_for_match(n.title or ""):
            return n
    return None


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

    if kind == "list_tasks_today":
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from cara.services import tasks as task_svc
        items = await task_svc.list_tasks(session, user_id=user_id, include_done=False)
        today = datetime.now(ZoneInfo("Europe/Rome")).date()
        # Today = due_date == today OR (no due_date AND created today).
        # We pick "anything due today, plus stuff with no due date that
        # was opened today" — practical for a household assistant.
        todays = []
        for t in items:
            if t.due_date and t.due_date.date() == today:
                todays.append(t)
            elif (not t.due_date) and t.created_at and t.created_at.date() == today:
                todays.append(t)
        if not todays:
            return "Per oggi non hai nulla in programma."
        body = "\n".join(f"• {t.title}" for t in todays[:10])
        more = f"\n…(+{len(todays) - 10} altre)" if len(todays) > 10 else ""
        return f"Cose di oggi:\n{body}{more}"

    if kind == "list_shopping":
        from cara.services import shopping as shop_svc
        items = await shop_svc.list_items(session, user_id=user_id)
        # Show only un-bought entries; bought items would just be noise.
        open_items = [s for s in items if not s.bought]
        if not open_items:
            return "La lista della spesa è vuota."
        def _row(s) -> str:
            qty = f" ({s.qty})" if getattr(s, "qty", None) else ""
            return f"• {s.title}{qty}"
        body = "\n".join(_row(s) for s in open_items[:15])
        more = f"\n…(+{len(open_items) - 15} altri)" if len(open_items) > 15 else ""
        return f"Sulla lista della spesa:\n{body}{more}"

    if kind == "list_notes":
        from cara.services import notes as notes_svc
        items = await notes_svc.list_notes(session, user_id=user_id)
        if not items:
            return "Non hai note salvate."
        # Notes can be long; show titles + first ~60 char of body.
        def _row(n) -> str:
            t = (n.title or "(senza titolo)").strip()
            preview = (n.body or "").strip().split("\n", 1)[0]
            if len(preview) > 60:
                preview = preview[:60].rstrip() + "…"
            return f"• {t}" + (f" — {preview}" if preview else "")
        body = "\n".join(_row(n) for n in items[:8])
        more = f"\n…(+{len(items) - 8} altre)" if len(items) > 8 else ""
        return f"Le tue note:\n{body}{more}"

    if kind == "list_appointments":
        # An "appointment" = (a) task with a due_date OR (b) task whose
        # title contains "appuntamento". The user's mental model treats
        # both as appointments — we'd rather surface too many here than
        # tell them there are none when there clearly are.
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        from cara.services import tasks as task_svc
        all_tasks = await task_svc.list_tasks(session, user_id=user_id, include_done=False)
        appts = [
            t for t in all_tasks
            if t.due_date is not None or "appuntament" in (t.title or "").lower()
        ]
        scope = (args.get("scope") or "all").lower()
        if not appts:
            return "Non hai appuntamenti in programma."
        tz = ZoneInfo("Europe/Rome")
        now = datetime.now(tz)
        today = now.date()
        tomorrow = today + timedelta(days=1)
        # Filter by scope. Title-only "appuntamento:" matches have no
        # due_date — we exclude them when the user asked a date scope.
        def _local_date(d):
            return d.astimezone(tz).date()
        if scope == "today":
            appts = [t for t in appts if t.due_date and _local_date(t.due_date) == today]
            head = "Appuntamenti di oggi"
        elif scope == "tomorrow":
            appts = [t for t in appts if t.due_date and _local_date(t.due_date) == tomorrow]
            head = "Appuntamenti di domani"
        elif scope == "tonight":
            appts = [
                t for t in appts
                if t.due_date and _local_date(t.due_date) == today
                and t.due_date.astimezone(tz).hour >= 18
            ]
            head = "Appuntamenti di stasera"
        elif scope == "weekend":
            # Saturday=5, Sunday=6 in Python's weekday().
            days_to_sat = (5 - today.weekday()) % 7
            sat = today + timedelta(days=days_to_sat)
            sun = sat + timedelta(days=1)
            appts = [
                t for t in appts
                if t.due_date and _local_date(t.due_date) in (sat, sun)
            ]
            head = "Appuntamenti del weekend"
        elif scope == "week":
            # "this week" = today through next Sunday (inclusive).
            days_to_sun = (6 - today.weekday()) % 7
            week_end = today + timedelta(days=days_to_sun)
            appts = [
                t for t in appts
                if t.due_date and today <= _local_date(t.due_date) <= week_end
            ]
            head = "Appuntamenti di questa settimana"
        elif scope == "next_week":
            # "next week" = next Monday through the Sunday after.
            days_to_mon = (7 - today.weekday()) % 7 or 7
            nw_start = today + timedelta(days=days_to_mon)
            nw_end = nw_start + timedelta(days=6)
            appts = [
                t for t in appts
                if t.due_date and nw_start <= _local_date(t.due_date) <= nw_end
            ]
            head = "Appuntamenti della prossima settimana"
        else:
            head = "I tuoi appuntamenti"
        if not appts:
            return f"{head.replace('I tuoi appuntamenti', 'Appuntamenti')}: nessuno."
        # Sort: tasks with due_date first (chronological), title-only
        # appointments after (by creation order).
        appts.sort(key=lambda t: (t.due_date is None, t.due_date or t.created_at))
        def _fmt(dt):
            local = dt.astimezone(tz)
            target = local.date()
            hhmm = local.strftime("%H:%M")
            if target == today:
                return f"oggi alle {hhmm}"
            if target == tomorrow:
                return f"domani alle {hhmm}"
            return local.strftime("%a %d/%m alle %H:%M")
        rows = []
        for t in appts[:10]:
            when = _fmt(t.due_date) if t.due_date else "senza data"
            rows.append(f"• {t.title} — {when}")
        more = f"\n…(+{len(appts) - 10} altri)" if len(appts) > 10 else ""
        return f"{head}:\n" + "\n".join(rows) + more

    if kind == "answer_weather":
        # Resolve family location from admin_settings. If unset, return
        # an actionable message instead of guessing a city.
        from cara.services import admin_settings as admin_svc
        from cara.services.weather import WeatherService

        scope = (args.get("scope") or "today").lower()
        override_city = (args.get("city") or "").strip() or None

        lat: float | None = None
        lon: float | None = None
        place_label = ""
        ws = WeatherService()

        if override_city:
            # User said "che tempo fa a Roma" — geocode on the fly.
            try:
                hits = await ws.geocode(override_city, count=1)
            except Exception:
                hits = []
            if not hits:
                return (
                    f"Non riesco a trovare \"{override_city}\". "
                    "Riprova con un nome di città più preciso."
                )
            lat, lon = hits[0].latitude, hits[0].longitude
            place_label = hits[0].name
        else:
            try:
                lat_v = await admin_svc.get(session, "family_lat")
                lon_v = await admin_svc.get(session, "family_lon")
                city_v = await admin_svc.get(session, "family_city")
            except Exception:
                lat_v = lon_v = city_v = None
            if lat_v is not None and lon_v is not None:
                lat = float(lat_v)
                lon = float(lon_v)
                place_label = str(city_v or "casa")
            else:
                return (
                    "Non ho ancora la città di casa. "
                    "Vai su /admin (Impostazioni → Residenza) e impostala, "
                    "poi richiedimi il meteo."
                )

        if scope == "today":
            cur = await ws.current(lat, lon)
            if cur is None:
                return f"Non riesco a leggere il meteo di {place_label} adesso."
            temp = round(cur.temperature_c)
            apparent = (
                f" (percepiti {round(cur.apparent_temperature_c)}°)"
                if cur.apparent_temperature_c is not None
                else ""
            )
            return (
                f"A {place_label}: {cur.label.lower()}, {temp}°{apparent}."
            )

        days = 7 if scope == "week" else 2  # tomorrow → fetch 2 to have day 1
        forecast = await ws.forecast(lat, lon, days=days)
        if not forecast:
            return f"Non riesco a leggere il meteo di {place_label}."

        if scope == "tomorrow":
            if len(forecast) < 2:
                return f"Previsione di domani per {place_label} non disponibile."
            d = forecast[1]
            return (
                f"Domani a {place_label}: {d.label.lower()}, "
                f"min {round(d.temp_min_c)}° / max {round(d.temp_max_c)}°."
            )

        # Week scope. DailyForecast.date is an ISO "YYYY-MM-DD" string.
        from datetime import date as _date
        days_it = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
        rows = []
        for d in forecast[:7]:
            try:
                dt = _date.fromisoformat(d.date)
                day_label = f"{days_it[dt.weekday()]} {dt.strftime('%d/%m')}"
            except (ValueError, TypeError):
                day_label = d.date
            rows.append(
                f"• {day_label}: {d.label.lower()}, "
                f"{round(d.temp_min_c)}°/{round(d.temp_max_c)}°"
            )
        return f"Meteo a {place_label}:\n" + "\n".join(rows)

    if kind == "complete_task":
        from cara.services import tasks as task_svc
        title = (args.get("title") or "").strip()
        if not title:
            return "Quale task hai completato?"
        match = await _find_task_by_title(session, user_id=user_id, title=title)
        if match is None:
            return f"Non trovo una task che si chiami \"{title}\"."
        if match.done:
            return f"\"{match.title}\" è già completata."
        await task_svc.update_task(session, match.id, user_id=user_id, done=True)
        return f"Segnata come fatta: \"{match.title}\"."

    if kind == "delete_task":
        from cara.services import tasks as task_svc
        title = (args.get("title") or "").strip()
        if not title:
            return "Quale task vuoi cancellare?"
        match = await _find_task_by_title(session, user_id=user_id, title=title)
        if match is None:
            return f"Non trovo una task che si chiami \"{title}\"."
        await task_svc.delete_task(session, match.id, user_id=user_id)
        return f"Eliminata: \"{match.title}\"."

    if kind == "duplicate_task":
        from cara.services import tasks as task_svc
        title = (args.get("title") or "").strip()
        if not title:
            return "Quale task vuoi duplicare?"
        match = await _find_task_by_title(session, user_id=user_id, title=title)
        if match is None:
            return f"Non trovo una task che si chiami \"{title}\"."
        new_t = await task_svc.create_task(
            session, user_id=user_id,
            title=match.title,
            due_date=match.due_date,
        )
        return f"Duplicata: \"{new_t.title}\"."

    if kind == "mark_shopping_bought":
        from cara.services import shopping as shop_svc
        title = (args.get("title") or "").strip()
        if not title:
            return "Cosa hai comprato?"
        match = await _find_shopping_by_title(session, user_id=user_id, title=title)
        if match is None:
            return f"Non vedo \"{title}\" nella tua lista della spesa."
        if match.bought:
            return f"\"{match.title}\" risulta già preso."
        await shop_svc.update_item(session, match.id, user_id=user_id, bought=True)
        return f"Segnato come preso: \"{match.title}\"."

    if kind == "delete_shopping":
        from cara.services import shopping as shop_svc
        title = (args.get("title") or "").strip()
        if not title:
            return "Cosa vuoi togliere dalla spesa?"
        match = await _find_shopping_by_title(session, user_id=user_id, title=title)
        if match is None:
            return f"Non vedo \"{title}\" nella tua lista."
        await shop_svc.delete_item(session, match.id, user_id=user_id)
        return f"Tolto dalla spesa: \"{match.title}\"."

    if kind == "add_note":
        from cara.services import notes as notes_svc
        body_text = (args.get("body") or "").strip()
        if not body_text:
            return "Cosa devo annotare?"
        # Use the first ~40 chars as title, rest as body.
        first_line = body_text.split("\n", 1)[0]
        if len(first_line) > 60:
            note_title = first_line[:60].rsplit(" ", 1)[0]
        else:
            note_title = first_line
        n = await notes_svc.create_note(
            session, user_id=user_id,
            title=note_title or "Nota",
            body=body_text,
        )
        return f"Nota salvata: \"{n.title}\"."

    if kind == "delete_note":
        from cara.services import notes as notes_svc
        title = (args.get("title") or "").strip()
        if not title:
            return "Quale nota vuoi cancellare?"
        match = await _find_note_by_title(session, user_id=user_id, title=title)
        if match is None:
            return f"Non trovo una nota che si chiami \"{title}\"."
        await notes_svc.delete_note(session, match.id, user_id=user_id)
        return f"Nota eliminata."

    if kind == "capabilities":
        return _CAPABILITIES_BLURB

    if kind == "identity":
        return "Sono Cara, l'assistente di casa della famiglia Pedoto. Ti aiuto con task, lista della spesa, note, appuntamenti, news, radio e altro. Per sapere tutto chiedimi \"cosa sai fare\"."

    if kind == "add_task":
        from cara.services import tasks as task_svc
        from cara.services.it_date_parser import parse_due, strip_date_phrase
        raw_title = args.get("title", "").strip()
        if not raw_title:
            return "Cosa devo aggiungere?"
        # Extract a natural-language date phrase from the title; if found,
        # set due_date AND strip the phrase from the title so the task
        # reads cleanly ("ricordami domani alle 9 di chiamare la zia"
        # → title="chiamare la zia", due_date=tomorrow 09:00).
        parsed = parse_due(raw_title)
        due = None
        if parsed:
            title = strip_date_phrase(raw_title, parsed) or raw_title
            due = parsed.when
        else:
            title = raw_title
        t = await task_svc.create_task(
            session, user_id=user_id, title=title, due_date=due,
        )
        if due is not None:
            from zoneinfo import ZoneInfo
            local = due.astimezone(ZoneInfo("Europe/Rome"))
            today = local.date() == local.now().date()
            tomorrow = (local.now().date() - local.date()).days == -1
            if today:
                when = f"oggi alle {local.strftime('%H:%M')}"
            elif tomorrow:
                when = f"domani alle {local.strftime('%H:%M')}"
            else:
                when = local.strftime("%a %d/%m alle %H:%M")
            return f"Aggiunto: \"{t.title}\" — {when}."
        return f"Aggiunto: \"{t.title}\"."

    if kind == "add_shopping":
        from cara.services import shopping as shop_svc
        title = args.get("title", "").strip()
        if not title:
            return "Cosa devo aggiungere alla spesa?"
        s = await shop_svc.create_item(session, user_id=user_id, title=title)
        return f"Messo nella spesa: \"{s.title}\"."

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
    try_quick_calc,
    try_smarthome,
    try_skill_dispatcher,
    try_recipe_chain,
    try_intent_router,
)
