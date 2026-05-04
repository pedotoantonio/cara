"""Chat completion endpoint with SSE streaming + persistence.

Wire format (SSE):

    event: meta
    data: {"conversation_id": "uuid"}

    event: token
    data: {"text": "Ciao", "token_id": 1234}

    event: done
    data: {"tokens": 42, "first_token_seconds": 0.31, ...}

    event: error
    data: {"detail": "..."}

If the request omits `conversation_id`, a new conversation is created and its
id is announced via the `meta` event before the first token. The full message
history is appended to the conversation in the DB so that subsequent requests
with the same `conversation_id` get context.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai import LLMService, get_llm_service
from cara.ai.llm import LLMUnavailableError
from cara.api.deps import get_current_user
from cara.cda import CdaError, DiscoverRequest, discover as cda_discover
from cara.cda.memory import content_kb as cda_kb
from cara.core import LumoState, get_bus, get_state_machine
from cara.services import event_log, intent_router
from cara.config import settings
from cara.models.user import User
from cara.schemas.chat import ChatMessage, ChatRequest
from cara.services import conversations as convo_svc
from cara.services import files as file_svc
from cara.services import recipe_chain
from cara.skills import dispatcher as skill_dispatcher
from cara.skills.executor import (
    SkillExecutionError,
    render_fallback as _skill_render_fallback,
    render_response as _skill_render_response,
    run as skill_run,
)
from cara.store import get_session

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["chat"])

_IM_START = "<|im_start|>"
_IM_END = "<|im_end|>"


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
        ctx = _runtime_context_message()
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
            logger.warning("chat.routed.who_is_home_error", error=str(exc))
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


def _render_qwen_prompt(messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    for m in messages:
        parts.append(f"{_IM_START}{m.role}\n{m.content}{_IM_END}\n")
    parts.append(f"{_IM_START}assistant\n")
    return "".join(parts)


# Persona tone presets — appended to the system prompt and (in privacy mode)
# also drop the historical messages from the prompt, mirroring Lumo's three
# tones (normale / neutro / sarcastico). Reset on every restart of the
# backend container is fine: this is intentionally non-persistent at the
# message layer (the key is in admin_settings, but no per-conversation
# override).
_TONE_DIRECTIVE = {
    "default": "",
    "privacy": (
        "\n\n## MODALITÀ PRIVACY ATTIVA\n"
        "Non usare il nome dell'utente. Non fare riferimento alla cronologia. "
        "Rispondi al turno corrente con il minimo di informazioni necessarie. "
        "Niente domande personali, niente memorie."
    ),
    "playful": (
        "\n\n## MODALITÀ SCHERZOSA ATTIVA\n"
        "Aggiungi un tocco di leggerezza e ironia gentile alle risposte, ma "
        "senza esagerare. Niente sarcasmo cattivo, niente prese in giro. "
        "Pensa a una zia simpatica che racconta cose. Resta concisa."
    ),
}


_WEEKDAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MONTHS_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


# ---------------------------------------------------------------------------
# Agent loop — forced grounding for info-need queries.
#
# When the user asks something the LLM is likely to hallucinate ("cos'è X",
# "chi è Y", "che tempo fa", "quanto costa Z"), or when the model itself
# emitted [TOOL: discover ...] indicating it knows it should look it up, we:
#  1. Run the CDA discover pipeline server-side.
#  2. Take the extracted article text.
#  3. Re-prompt the LLM with that text injected as a system message.
#  4. Stream the second pass as a `revision` SSE event so the frontend
#     replaces the (potentially hallucinated) first reply.
# ---------------------------------------------------------------------------

_GROUND_PATTERNS = [
    r"\bcos[a']?\s*[èe']\b",            # cos'è, cosa è
    r"\bchi\s*[èe]\b",                   # chi è
    r"\bdove\s+(?:[èe]|si\s+trova)\b",
    r"\bquando\s+(?:[èe]|sarà|è\s+stato)\b",
    r"\bspiegami\b",
    r"\bdefinisci\b",
    r"\bche\s+(?:vuol\s+dire|significa)\b",
    r"\bdimmi\s+(?:cosa|chi|dove|quando)\b",
    r"\bmeteo\b",
    r"\bprevisioni\b",
    r"\bvincitore\b",
    r"\bquanto\s+costa\b",
    r"\bin\s+che\s+anno\b",
    r"\bha\s+vinto\b",
    r"\bè\s+vero\s+che\b",
]
_GROUND_RE = re.compile("|".join(_GROUND_PATTERNS), re.IGNORECASE)


def _needs_grounding(question: str) -> bool:
    """True if the user's question likely needs grounded information."""
    return bool(_GROUND_RE.search(question or ""))


def _infer_kind(question: str) -> str:
    """Cheap classifier: pick the right `kind` for discover from the question."""
    q = (question or "").lower()
    if re.search(r"\b(podcast|puntata)\b", q):
        return "podcast"
    if re.search(r"\b(ascolta|ascoltare|radio|musica)\b", q):
        return "audio_stream"
    if re.search(r"\b(video|trailer|guarda)\b", q):
        return "video"
    if re.search(r"\b(foto|immagine|immagini)\b", q):
        return "image"
    return "article"


def _has_discover_tool(text: str) -> bool:
    """Best-effort detection of the model emitting any `discover` tool call,
    tolerant of the 1.5B's typical typos (TOOL/TUPO/TWOOL/TU prefix)."""
    return bool(re.search(r"\[\s*[A-Z_]*\s*:?\s*discover\b", text, flags=re.IGNORECASE))


_AGENT_GROUNDING_SUFFIX = (
    "Usa SOLO questa informazione per rispondere all'ultima domanda dell'utente. "
    "Rispondi in italiano, in 2-4 frasi, in modo naturale e conciso. "
    "Se la fonte non contiene la risposta, dillo onestamente. "
    "NON emettere [TOOL: ...] in questa risposta."
)



def _runtime_context_message() -> str:
    """Date, time and timezone — injected into the prompt as a system message
    on every turn so the model knows where/when it is.

    Without this, the 1.5B happily anchors to its training-data cutoff
    (e.g. "oggi è il 28 settembre 2023") and refuses date queries on the
    grounds that "non ho accesso alla data corrente".

    We pre-compute common derivations (current month name, days to Christmas,
    days to next New Year's Eve) because the 1.5B can't do date arithmetic
    reliably — observed in QA "tra quanto tempo è Natale?" → "tra 19 giorni
    e 4 giorni" (nonsense), and "in che mese siamo?" → "siamo in marzo"
    even with the date already shown.
    """
    now = datetime.now(ZoneInfo("Europe/Rome"))
    today_date = now.date()
    # Next Christmas / New Year (this year if not yet passed, else next year).
    from datetime import date

    christmas_year = now.year if today_date <= date(now.year, 12, 25) else now.year + 1
    days_to_xmas = (date(christmas_year, 12, 25) - today_date).days
    new_year_target = date(now.year + 1, 1, 1) if today_date > date(now.year, 1, 1) else date(now.year, 1, 1)
    days_to_new_year = (new_year_target - today_date).days

    return (
        "## CONTESTO RUNTIME (informazioni precise, NON cercare su internet, NON ricalcolare)\n"
        f"- Oggi è {_WEEKDAYS_IT[now.weekday()]} {now.day} {_MONTHS_IT[now.month - 1]} {now.year}.\n"
        f"- Mese corrente: {_MONTHS_IT[now.month - 1]}. Anno corrente: {now.year}.\n"
        f"- Ora attuale: {now.hour:02d}:{now.minute:02d} (fuso Europe/Rome, Italia).\n"
        f"- Giorni mancanti al prossimo Natale (25 dicembre): {days_to_xmas}.\n"
        f"- Giorni mancanti al prossimo Capodanno (1 gennaio): {days_to_new_year}.\n"
        "Per domande su \"che giorno/ora/mese/anno è\", \"tra quanto tempo è Natale\", "
        "\"tra quanto è Capodanno\" rispondi DIRETTAMENTE con il dato sopra, "
        "SENZA usare il tool discover e SENZA fare aritmetica tu stesso."
    )


def _sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


@router.post("/chat", response_class=StreamingResponse)
async def chat(
    req: ChatRequest,
    conversation_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),  # noqa: B008
    llm: LLMService = Depends(get_llm_service),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> StreamingResponse:
    # Resolve or create conversation up-front so we can announce the id and
    # persist the user message before generation starts.
    if conversation_id is not None:
        convo = await convo_svc.get_conversation(session, conversation_id, user_id=user.id)
        if convo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    else:
        # Auto-title from the first user message (truncated). Saves a round-trip.
        first_user = next((m.content for m in req.messages if m.role == "user"), None)
        title = (first_user or "Nuova conversazione")[:80]
        convo = await convo_svc.create_conversation(session, user_id=user.id, title=title)
        # Seed the new conversation with the CARA persona system message so that
        # it persists in the history and is included in every subsequent turn.
        from cara.services import admin_settings as setting_svc

        sysprompt = await setting_svc.get_with_env_fallback(
            session, "llm_system_prompt", settings.llm_system_prompt
        )
        await convo_svc.add_message(
            session, conversation_id=convo.id, role="system", content=sysprompt,
        )

    # Resolve attached files first so we can fold their text directly into
    # the user turn. Persisting a separate "FILE ALLEGATI..." message in the
    # same transaction caused ordering ambiguity (Postgres `now()` is
    # statement-time, every message in one commit shares `created_at`).
    attached_files = (
        await file_svc.files_by_ids(session, req.file_ids, user_id=user.id)
        if req.file_ids
        else []
    )

    # Guard rail: if attachments are all empty (e.g. scanned PDFs without OCR),
    # skip the LLM entirely and return an honest canned reply. The 1.5B
    # otherwise hallucinates "non posso accedere ai file" regardless of how
    # the prompt is phrased.
    if attached_files and not any(file_svc.has_extractable_text(f) for f in attached_files):
        names = ", ".join(f.filename for f in attached_files)
        canned = (
            f"Ho ricevuto {names} ma non sono riuscita a estrarre il testo. "
            "Se è un PDF scannerizzato (immagine, non testo selezionabile) serve "
            "OCR, che non è ancora supportato in locale. "
            "Prova a riconvertirlo in PDF testuale o caricarlo come .docx / .txt."
        )
        for m in [mm for mm in req.messages if mm.role == "user"]:
            await convo_svc.add_message(
                session, conversation_id=convo.id, role="user", content=m.content
            )
        await convo_svc.add_message(
            session, conversation_id=convo.id, role="assistant", content=canned
        )
        await session.commit()
        convo_id_str = str(convo.id)

        async def _canned_stream() -> AsyncIterator[bytes]:
            yield _sse("meta", {"conversation_id": convo_id_str})
            yield _sse("token", {"text": canned, "token_id": -1})
            yield _sse(
                "done",
                {
                    "conversation_id": convo_id_str,
                    "tokens": 0,
                    "first_token_seconds": 0.0,
                    "total_seconds": 0.0,
                    "tokens_per_second": 0.0,
                },
            )

        return StreamingResponse(
            _canned_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    file_block = file_svc.files_to_prompt_block(attached_files) if attached_files else ""

    # Persist incoming user messages. The file block is appended to the LAST
    # user message so the model sees it next to the question it has to answer.
    user_msgs = [m for m in req.messages if m.role == "user"]
    for idx, m in enumerate(user_msgs):
        content = m.content
        if file_block and idx == len(user_msgs) - 1:
            content = f"{m.content}\n\n{file_block}"
        await convo_svc.add_message(
            session, conversation_id=convo.id, role="user", content=content
        )

    await session.commit()

    if attached_files:
        logger.info(
            "chat.attachments",
            count=len(attached_files),
            kinds=[f.kind for f in attached_files],
            total_text_chars=sum(len(f.text_content or "") for f in attached_files),
        )

    last_user_q = next(
        (m.content for m in reversed(req.messages) if m.role == "user"), ""
    )

    # ---- Tier-0: pure-noise bypass --------------------------------------
    # Only fires for transcripts that are CLEARLY filler/junk:
    #   - <3 alphanumeric chars total (e.g. "" or "ah" or just punctuation)
    #   - the whole query is exactly one canonical filler word
    # NB: legitimate short Italian words like "ciao", "stop", "bene", "luce"
    # MUST go to the LLM. Earlier tighter thresholds were misclassifying
    # them as noise.
    NOISE_RE = re.compile(
        r"^(?:ehm|uhm|mhm?|hmm?|ok|boh)\s*[?!.]*$",
        re.IGNORECASE,
    )
    stripped = re.sub(r"[^a-zA-Z0-9àèéìòù]", "", last_user_q.lower())
    is_noise = (
        last_user_q
        and not attached_files
        and (len(stripped) < 3 or bool(NOISE_RE.match(last_user_q.strip())))
    )
    if is_noise:
        canned = "Non ho capito bene, puoi ripetere?"
        # User messages were already persisted above; only add the assistant.
        await convo_svc.add_message(
            session, conversation_id=convo.id, role="assistant", content=canned,
        )
        await session.commit()
        convo_id_str_n = str(convo.id)
        logger.info("chat.noise_bypass", query=last_user_q[:60])
        event_log.record(
            "chat.noise_bypass",
            user_id=user.id,
            duration_ms=0,
            query=last_user_q[:80],
        )
        get_bus().emit(
            "chat.noise_bypass",
            {"user_id": user.id, "query": last_user_q[:80]},
        )
        get_state_machine().mark_activity()

        async def _noise_stream() -> AsyncIterator[bytes]:
            yield _sse("meta", {"conversation_id": convo_id_str_n})
            yield _sse("token", {"text": canned, "token_id": -1})
            yield _sse(
                "done",
                {
                    "conversation_id": convo_id_str_n,
                    "tokens": 0,
                    "first_token_seconds": 0.0,
                    "total_seconds": 0.0,
                    "tokens_per_second": 0.0,
                    "routed": "noise",
                },
            )

        return StreamingResponse(
            _noise_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- Tier-0.4: Skill Factory dispatcher (Tier-1 regex match) --------
    # Looks up the user's message against the active skills in the DB. If a
    # skill matches, executes its plan via the deterministic Executor and
    # returns a one-shot SSE response. This is the data-driven replacement
    # for the per-case hardcoded chains (Step 65 recipe_chain). See
    # `/opt/cara/docs/skill-factory-extension-prompt.md`.
    skill_match = (
        await skill_dispatcher.match(session, last_user_q)
        if last_user_q and not attached_files
        else None
    )
    if skill_match is not None:
        sk, slots = skill_match
        try:
            ctx = await skill_run(session, skill=sk, user_id=user.id, slots=slots)
            summary = _skill_render_response(sk, ctx)
            routed_label = f"skill:{sk.name}"
        except SkillExecutionError as exc:
            logger.warning(
                "chat.skill_run_failed", skill=sk.name, step=exc.step_id,
                error=str(exc.cause),
            )
            summary = _skill_render_fallback(sk, dict(slots), str(exc.cause))
            routed_label = f"skill_fallback:{sk.name}"
        await convo_svc.add_message(
            session, conversation_id=convo.id, role="assistant", content=summary,
        )
        await session.commit()
        convo_id_str_s = str(convo.id)
        logger.info("chat.skill_run", skill=sk.name, slots=slots, summary_len=len(summary))
        get_state_machine().mark_activity()

        async def _skill_stream() -> AsyncIterator[bytes]:
            yield _sse("meta", {"conversation_id": convo_id_str_s})
            yield _sse("token", {"text": summary, "token_id": -1})
            yield _sse(
                "done",
                {
                    "conversation_id": convo_id_str_s,
                    "tokens": 0,
                    "first_token_seconds": 0.0,
                    "total_seconds": 0.0,
                    "tokens_per_second": 0.0,
                    "routed": routed_label,
                },
            )

        return StreamingResponse(
            _skill_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- Tier-0.5: server-side recipe → ingredients chain (LEGACY) -----
    # Kept as fallback in case the corresponding skill in DB is disabled.
    # The active `ricetta_to_spesa` skill above handles this pattern via
    # the dispatcher; this branch only fires when the skill is missing.
    recipe_dish = (
        recipe_chain.detect_intent(last_user_q)
        if last_user_q and not attached_files
        else None
    )
    if recipe_dish:
        try:
            summary = await recipe_chain.run(session, user_id=user.id, dish=recipe_dish)
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat.recipe_chain_failed", dish=recipe_dish, error=str(exc))
            summary = (
                f"Ho avuto un problema cercando la ricetta di {recipe_dish}. "
                "Riprova fra un momento."
            )
        await convo_svc.add_message(
            session, conversation_id=convo.id, role="assistant", content=summary,
        )
        await session.commit()
        convo_id_str_r = str(convo.id)
        logger.info("chat.recipe_chain", dish=recipe_dish, summary_len=len(summary))
        get_state_machine().mark_activity()

        async def _recipe_stream() -> AsyncIterator[bytes]:
            yield _sse("meta", {"conversation_id": convo_id_str_r})
            yield _sse("token", {"text": summary, "token_id": -1})
            yield _sse(
                "done",
                {
                    "conversation_id": convo_id_str_r,
                    "tokens": 0,
                    "first_token_seconds": 0.0,
                    "total_seconds": 0.0,
                    "tokens_per_second": 0.0,
                    "routed": "recipe_chain",
                },
            )

        return StreamingResponse(
            _recipe_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- Tier-1: deterministic intent router ----------------------------
    #
    # Catch the canonical commands ("metti rai radio 1", "che giorno è oggi",
    # "cosa devo fare", "cos'è X", …) BEFORE the LLM is invoked. Saves 6-90 s
    # of token latency and avoids the 1.5B's tool-emission typos. Anything
    # ambiguous falls through to the regular flow.
    routed = intent_router.match(last_user_q) if last_user_q and not attached_files else None
    if routed is not None:
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
        _elapsed = int((_t.perf_counter() - _t0) * 1000)
        await convo_svc.add_message(
            session, conversation_id=convo.id, role="assistant", content=canned,
        )
        await session.commit()
        convo_id_str_r = str(convo.id)
        logger.info(
            "chat.intent_routed",
            kind=routed.kind, args=routed.args, reply_chars=len(canned),
        )
        event_log.record(
            "intent_router.match",
            user_id=user.id,
            duration_ms=_elapsed,
            intent=routed.kind,
            query=last_user_q[:80],
            args=routed.args,
        )
        bus.emit(
            "chat.routed.done",
            {
                "user_id": user.id,
                "intent": routed.kind,
                "duration_ms": _elapsed,
                "reply_chars": len(canned),
            },
        )
        sm.transition(LumoState.SPEAKING)
        sm.transition(LumoState.IDLE)

        async def _routed_stream() -> AsyncIterator[bytes]:
            yield _sse("meta", {"conversation_id": convo_id_str_r})
            yield _sse("token", {"text": canned, "token_id": -1})
            yield _sse(
                "done",
                {
                    "conversation_id": convo_id_str_r,
                    "tokens": 0,
                    "first_token_seconds": 0.0,
                    "total_seconds": 0.0,
                    "tokens_per_second": 0.0,
                    "routed": routed.kind,
                },
            )

        return StreamingResponse(
            _routed_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- Early-bypass: did we already answer this question once? ----
    #
    # If the user query needs grounding AND we have a cached answer in the KB,
    # skip BOTH LLM passes entirely and stream the learned answer back. This
    # is what makes CARA "learn from the internet": the second time the same
    # question comes in, response is ~150 ms instead of ~90 s.
    #
    # Conservative: only fires when there are no attached files (those need
    # the LLM to reason about specific content) and only on info-need queries.
    if (
        not attached_files
        and last_user_q
        and _needs_grounding(last_user_q)
    ):
        try:
            kb_hits = await cda_kb.list_active_for_query(
                session, query=last_user_q, content_type="article", limit=1
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat.kb_lookup_failed", error=str(exc))
            kb_hits = []
        if kb_hits:
            cached_answer = (kb_hits[0].metadata_ or {}).get("cached_answer")
            cached_domain = kb_hits[0].source_domain
            if cached_answer and isinstance(cached_answer, str):
                attribution = (
                    f"\n\n*(fonte: {cached_domain})*" if cached_domain else ""
                )
                final_canned = cached_answer + attribution
                # Persist the assistant message immediately so the conversation
                # history stays consistent with the streamed response.
                await convo_svc.add_message(
                    session,
                    conversation_id=convo.id,
                    role="assistant",
                    content=final_canned,
                )
                await session.commit()
                convo_id_str_e = str(convo.id)
                logger.info(
                    "chat.kb_bypass.applied",
                    query=last_user_q[:80],
                    domain=cached_domain,
                    answer_chars=len(final_canned),
                )
                event_log.record(
                    "chat.kb_cached",
                    user_id=user.id,
                    duration_ms=0,
                    query=last_user_q[:80],
                    domain=cached_domain,
                )

                async def _kb_bypass_stream() -> AsyncIterator[bytes]:
                    yield _sse("meta", {"conversation_id": convo_id_str_e})
                    yield _sse("token", {"text": final_canned, "token_id": -1})
                    yield _sse(
                        "done",
                        {
                            "conversation_id": convo_id_str_e,
                            "tokens": 0,
                            "first_token_seconds": 0.0,
                            "total_seconds": 0.0,
                            "tokens_per_second": 0.0,
                        },
                    )

                return StreamingResponse(
                    _kb_bypass_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                )

    # Render prompt from the full DB history so multi-turn works.
    history = await convo_svc.history_for_prompt(session, convo.id)

    # Budget guard: keep the last user/assistant turn full-fidelity, truncate
    # older messages aggressively. Files attached in past turns ballooned the
    # prompt; truncating prevents the 1.5B from running out of its 4 K
    # context window and emitting zero tokens.
    OLDER_MSG_CAP = 400  # chars
    last_idx = len(history) - 1
    prompt_messages: list[ChatMessage] = []
    for i, m in enumerate(history):
        content = m.content
        if i < last_idx and m.role != "system" and len(content) > OLDER_MSG_CAP:
            content = content[:OLDER_MSG_CAP] + "\n[…]"
        prompt_messages.append(ChatMessage(role=m.role, content=content))  # type: ignore[arg-type]

    from cara.services import admin_settings as setting_svc
    sysprompt_active = await setting_svc.get_with_env_fallback(
        session, "llm_system_prompt", settings.llm_system_prompt
    )

    # Tone preset — appends a directive and, in "privacy" mode, also strips
    # the conversation history so the model only sees the current turn.
    tone_preset = await setting_svc.get(session, "tone_preset")
    tone_preset = tone_preset if tone_preset in _TONE_DIRECTIVE else "default"
    tone_directive = _TONE_DIRECTIVE.get(tone_preset, "")
    if tone_directive:
        sysprompt_active = sysprompt_active + tone_directive

    # Privacy mode: drop ALL prior messages so the model can't echo back
    # personal context. Keep only the persona prompt + last user turn.
    if tone_preset == "privacy":
        last_user = next(
            (pm for pm in reversed(prompt_messages) if pm.role == "user"), None,
        )
        prompt_messages = [pm for pm in prompt_messages if pm.role == "system"]
        if last_user is not None:
            prompt_messages.append(last_user)

    # Strip any pre-existing system messages and inject a fresh one with
    # the current tone directive applied. (The DB seed is from a prior
    # state where the directive may not have been on yet.)
    prompt_messages = [pm for pm in prompt_messages if pm.role != "system"]
    prompt_messages.insert(0, ChatMessage(role="system", content=sysprompt_active))

    # Inject the runtime context (date/time/timezone) as a separate system
    # message right after the persona. Generated fresh each turn so the model
    # always has the current date — without this it anchors to its training
    # cutoff and refuses date queries.
    runtime_ctx = ChatMessage(role="system", content=_runtime_context_message())
    insert_pos = 0
    for i, pm in enumerate(prompt_messages):
        if pm.role == "system":
            insert_pos = i + 1
        else:
            break
    prompt_messages.insert(insert_pos, runtime_ctx)

    # Cognitive mode (admin opt-in): prepend the full reasoning prompt above
    # the persona prompt so the model has it as the very first instruction.
    cog_on = await setting_svc.get(session, "cognitive_mode")
    if cog_on:
        cog_prompt = await setting_svc.get_with_env_fallback(
            session, "llm_cognitive_prompt", settings.llm_cognitive_prompt
        )
        prompt_messages.insert(
            0, ChatMessage(role="system", content=cog_prompt)
        )

    # FOCUS line — inserted RIGHT BEFORE the last user message so the model
    # doesn't drift to a previous turn's question (a 1.5B failure mode when
    # the conversation history is fresh in context). Also reminds the model
    # that the latest input is what it must answer.
    last_user_idx = -1
    for i in range(len(prompt_messages) - 1, -1, -1):
        if prompt_messages[i].role == "user":
            last_user_idx = i
            break
    if last_user_idx >= 0:
        focus_msg = ChatMessage(
            role="system",
            content=(
                "## FOCUS DEL TURNO\n"
                "L'utente ha appena scritto la domanda qui sotto. "
                "Rispondi SOLO a questa domanda. Non rispondere a domande "
                "precedenti. Se non hai capito, di' 'non ho capito, "
                "puoi ripetere?' invece di inventare."
            ),
        )
        prompt_messages.insert(last_user_idx, focus_msg)

    prompt = _render_qwen_prompt(prompt_messages)
    # Roughly, Qwen2.5 tokenises Italian at ~3.5 chars/token. Logging char
    # length lets us spot context overflows before the model goes silent.
    logger.info(
        "chat.prompt_built",
        prompt_chars=len(prompt),
        approx_tokens=len(prompt) // 4,
        n_messages=len(prompt_messages),
    )

    convo_id_str = str(convo.id)

    # ---- LLM quality mode hot-swap ----------------------------------------
    # If the admin has flipped the runtime variant since the last request,
    # swap before generation. The swap takes ~10 s once per change; idle
    # otherwise. We tolerate failure (stick with the current variant).
    desired_mode = await setting_svc.get(session, "llm_quality_mode")
    if desired_mode and desired_mode in (llm.available_modes if hasattr(llm, "available_modes") else []):
        if desired_mode != llm.mode:
            try:
                await llm.set_mode(desired_mode)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "chat.llm_mode_switch_failed",
                    desired=desired_mode, current=llm.mode, error=str(exc),
                )

    # Resolve effective max_new_tokens: explicit request wins; otherwise admin
    # override; otherwise env default.
    if req.max_new_tokens is not None:
        effective_max = req.max_new_tokens
    else:
        admin_max = await setting_svc.get(session, "llm_max_new_tokens")
        effective_max = int(admin_max) if admin_max else settings.llm_max_new_tokens

    async def stream() -> AsyncIterator[bytes]:
        yield _sse("meta", {"conversation_id": convo_id_str})

        sm = get_state_machine()
        bus = get_bus()
        sm.transition(LumoState.THINKING)
        bus.emit(
            "chat.llm.start",
            {"user_id": user.id, "prompt_chars": len(prompt)},
        )

        t_start = time.monotonic()
        t_first: float | None = None
        n = 0
        buf: list[str] = []
        try:
            async for chunk in llm.generate(prompt, max_new_tokens=effective_max):
                if t_first is None:
                    t_first = time.monotonic() - t_start
                    sm.transition(LumoState.SPEAKING)
                    bus.emit(
                        "chat.llm.first_token",
                        {"user_id": user.id, "first_token_seconds": round(t_first, 3)},
                    )
                n += 1
                buf.append(chunk.text)
                yield _sse("token", {"text": chunk.text, "token_id": chunk.token_id})
        except LLMUnavailableError as exc:
            logger.warning("chat.llm_unavailable", error=str(exc))
            yield _sse("error", {"detail": str(exc)})
            return
        except Exception as exc:  # pragma: no cover
            logger.exception("chat.unhandled")
            yield _sse("error", {"detail": f"internal error: {exc!r}"})
            return

        t_total = time.monotonic() - t_start
        full_text = "".join(buf)
        # The text we eventually persist + return; may be replaced by the
        # self-critique pass below if validation is on and the verdict is RIVEDI.
        final_text = full_text

        # Persist the assistant turn. Open a fresh session because the request
        # session is closed by the time the stream yields its last bytes.
        from cara.store.db import _sessionmaker  # local import to avoid cycles
        from cara.services import admin_settings as setting_svc

        last_user = next(
            (m.content for m in reversed(req.messages) if m.role == "user"),
            "",
        )

        # --- agent loop: forced grounding for info-need queries ---
        # Triggers when (a) the LLM emitted a discover tool, or (b) the user
        # asked an "info-need" question and the LLM produced free-form prose
        # (likely hallucinated). The CDA discovers an article server-side and
        # we re-prompt the LLM with the article text.
        agent_loop_fired = False
        if _sessionmaker is not None and full_text and last_user:
            async with _sessionmaker() as s_a:
                agent_enabled = await setting_svc.get(s_a, "cda_agent_loop_enabled")
            # Default ON: if the flag is missing or None, treat as enabled.
            agent_enabled = True if agent_enabled in (None, True) else bool(agent_enabled)

            wants_loop = (
                agent_enabled
                and (_has_discover_tool(full_text) or _needs_grounding(last_user))
            )

            if wants_loop:
                kind = _infer_kind(last_user)
                discovered = None
                async with _sessionmaker() as s_a:
                    try:
                        discovered = await cda_discover(
                            s_a,
                            DiscoverRequest(
                                user_id=user.id,
                                raw_query=last_user,
                                content_type=kind,  # type: ignore[arg-type]
                            ),
                        )
                        await s_a.commit()
                    except CdaError as exc:
                        logger.info("chat.agent_loop.discover_failed", error=str(exc))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("chat.agent_loop.discover_error", error=str(exc))

                article_text = ""
                if discovered:
                    article_text = (discovered.metadata.get("text") or "").strip()  # type: ignore[union-attr]

                # If we got actual prose (not just a stream URL or empty), do a
                # second pass with the article in the prompt as a system message.
                if discovered and article_text and len(article_text) > 80 and kind == "article":
                    grounding = ChatMessage(
                        role="system",
                        content=(
                            "## INFORMAZIONE TROVATA SU INTERNET\n"
                            f"Fonte: {discovered.source_domain or 'web'}\n"
                            f"Titolo: {discovered.title or ''}\n\n"
                            f"{article_text[:1800]}\n\n"
                            f"{_AGENT_GROUNDING_SUFFIX}"
                        ),
                    )
                    # Insert the grounding right BEFORE the last user message
                    # so the model sees: persona → runtime → grounding → user.
                    new_msgs = list(prompt_messages)
                    insert_at = len(new_msgs)
                    for i in range(len(new_msgs) - 1, -1, -1):
                        if new_msgs[i].role == "user":
                            insert_at = i
                            break
                    new_msgs.insert(insert_at, grounding)
                    new_prompt = _render_qwen_prompt(new_msgs)
                    logger.info(
                        "chat.agent_loop.second_pass.start",
                        prompt_chars=len(new_prompt),
                        article_chars=len(article_text),
                        source=discovered.source_domain,
                    )
                    second_buf: list[str] = []
                    try:
                        async for chunk in llm.generate(new_prompt, max_new_tokens=240):
                            second_buf.append(chunk.text)
                    except LLMUnavailableError as exc:
                        logger.warning("chat.agent_loop.second_pass.llm_unavailable", error=str(exc))

                    second_text = "".join(second_buf).strip()
                    if second_text:
                        # Append a footer with the source so the user sees attribution
                        # right in the chat bubble.
                        attribution = ""
                        if discovered.source_domain:
                            attribution = f"\n\n*(fonte: {discovered.source_domain})*"
                        final_text = second_text + attribution
                        yield _sse("revision", {"text": final_text})
                        agent_loop_fired = True
                        logger.info(
                            "chat.agent_loop.applied",
                            before_len=len(full_text),
                            after_len=len(final_text),
                            kind=kind,
                        )
                        event_log.record(
                            "chat.agent_loop",
                            user_id=user.id,
                            duration_ms=int((time.monotonic() - t_start) * 1000),
                            content_kind=kind,
                            domain=discovered.source_domain,
                            answer_chars=len(final_text),
                        )
                        # Persist the answer back to the KB so the next time
                        # the same question is asked we can early-bypass both
                        # LLM passes entirely.
                        try:
                            async with _sessionmaker() as s_save:
                                await cda_kb.attach_cached_answer(
                                    s_save,
                                    discovered.content_id,
                                    second_text,  # store WITHOUT the attribution suffix
                                )
                                await s_save.commit()
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "chat.agent_loop.cache_save_failed", error=str(exc)
                            )
                elif discovered and kind != "article":
                    # For audio_stream/video/podcast/image we don't do a 2nd pass:
                    # the client opens the player from the parsed [TOOL: discover ...]
                    # in the first reply. Logged for observability.
                    logger.info(
                        "chat.agent_loop.skipped_non_article",
                        kind=kind,
                        url=discovered.url,
                    )

        # --- self-critique pass (opt-in via admin flag `validation_enabled`) ---
        # Only runs if the agent loop did NOT fire (otherwise it's redundant
        # and just doubles latency). Skipped for tool-emitting replies because
        # those have structured ground truth already.
        if (
            not agent_loop_fired
            and _sessionmaker is not None
            and full_text
            and "[" not in full_text
        ):
            async with _sessionmaker() as s_v:
                v_enabled = await setting_svc.get(s_v, "validation_enabled")
                v_prompt = await setting_svc.get_with_env_fallback(
                    s_v, "llm_validation_prompt", settings.llm_validation_prompt
                )
                v_max = await setting_svc.get_with_env_fallback(
                    s_v, "llm_validation_max_tokens", settings.llm_validation_max_tokens
                )
            if v_enabled:
                try:
                    rewrite = await llm.validate(
                        question=last_user,
                        answer=full_text,
                        validation_prompt=v_prompt,
                        max_new_tokens=int(v_max) if v_max else settings.llm_validation_max_tokens,
                    )
                except LLMUnavailableError as exc:
                    logger.warning("chat.validation_failed", error=str(exc))
                    rewrite = None
                if rewrite and rewrite != full_text:
                    final_text = rewrite
                    yield _sse("revision", {"text": rewrite})
                    logger.info(
                        "chat.validation_rewrite",
                        before_len=len(full_text),
                        after_len=len(rewrite),
                    )

        if _sessionmaker is not None and final_text:
            async with _sessionmaker() as s2:
                await convo_svc.add_message(
                    s2,
                    conversation_id=convo.id,
                    role="assistant",
                    content=final_text,
                    token_count=n,
                    latency_ms=int(t_total * 1000),
                    first_token_ms=int((t_first or 0.0) * 1000),
                )
                await s2.commit()

        bus.emit(
            "chat.llm.done",
            {
                "user_id": user.id,
                "tokens": n,
                "total_seconds": round(t_total, 2),
                "agent_loop_fired": agent_loop_fired,
            },
        )
        sm.transition(LumoState.IDLE)
        yield _sse(
            "done",
            {
                "conversation_id": convo_id_str,
                "tokens": n,
                "first_token_seconds": round(t_first or 0.0, 3),
                "total_seconds": round(t_total, 2),
                "tokens_per_second": round(n / max(t_total, 1e-6), 2),
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/health")
async def chat_health(llm: LLMService = Depends(get_llm_service)) -> dict:  # noqa: B008
    try:
        return {"status": "ok", "model_path": str(llm._model_path.name)}  # noqa: SLF001
    except LLMUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
