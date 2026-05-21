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

import asyncio
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
from cara.ai import kv_cache
from cara.ai.llm import LLMUnavailableError
from cara.learning import episodic, semantic
from cara.api.deps import get_current_user
from cara.api.v1._chat_grounding import (
    has_discover_tool as _has_discover_tool,
    infer_kind as _infer_kind,
    needs_grounding as _needs_grounding,
)
from cara.api.v1._chat_prompt import (
    AGENT_GROUNDING_SUFFIX as _AGENT_GROUNDING_SUFFIX,
    MONTHS_IT as _MONTHS_IT,
    TONE_DIRECTIVE as _TONE_DIRECTIVE,
    WEEKDAYS_IT as _WEEKDAYS_IT,
    render_qwen_prompt as _render_qwen_prompt,
    runtime_context_message as _runtime_context_message,
)
from cara.api.v1._chat_pipeline import route_chat_request
from cara.api.v1._chat_sse import sse_frame as _sse
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

# `_IM_START` / `_IM_END` were only consumed by `_render_qwen_prompt`,
# which now lives in `_chat_prompt`. Kept here as module-level aliases
# in case any other reader (or future tool-call parser) imports them.
_IM_START = "<|im_start|>"
_IM_END = "<|im_end|>"


# `_resolve_routed_intent` and the per-tier routing handlers (Tier-0.4
# skill dispatcher, Tier-0.5 recipe chain, Tier-1 intent router) were
# moved to `cara/api/v1/_chat_routing.py` (Step 0.2 phase C). The
# orchestrator below walks `ROUTING_TIERS` in order and returns the
# first non-None `StreamingResponse`.


# ---------------------------------------------------------------------------
# Helpers extracted to sibling modules (Step 0.2 refactor):
# - `_render_qwen_prompt`, `_runtime_context_message`,
#   `_TONE_DIRECTIVE`, `_WEEKDAYS_IT`, `_MONTHS_IT`,
#   `_AGENT_GROUNDING_SUFFIX` → `_chat_prompt.py`
# - `_needs_grounding`, `_infer_kind`, `_has_discover_tool` → `_chat_grounding.py`
# - `_sse` → `_chat_sse.py`
# Imported above with the same underscore names so the orchestrator
# below didn't change.
# ---------------------------------------------------------------------------


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

    # Fire-and-forget fact extraction on the LAST user message. Uses its
    # own session, never blocks the chat reply, never raises into the hot
    # path (errors are logged inside the helper). See feedback memory
    # `feedback_lazy_global_imports` — extract_facts_async resolves the
    # sessionmaker via `get_sessionmaker()`, not the lifespan global.
    if user_msgs:
        _last_user_content = user_msgs[-1].content
        asyncio.create_task(
            semantic.extract_facts_async(
                user_id=user.id,
                message=_last_user_content,
                source_ref=f"conversation:{convo.id}",
            )
        )

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

    # ---- Routing pipeline (Step 0.2 phase D) --------------------------
    #
    # The 3 deterministic routing tiers (skill / recipe / intent) are
    # wrapped as Stage objects in `cara.api.v1._chat_pipeline.CHAT_PIPELINE`.
    # `route_chat_request` builds a RouteContext, walks the pipeline,
    # records per-stage telemetry as `router.stage` events in episodic
    # memory, and returns a StreamingResponse if any stage handled the
    # request — or None if every stage missed (we then fall through to
    # the LLM).
    pipeline_resp = await route_chat_request(
        session=session,
        user=user,
        last_user_q=last_user_q,
        attached_files=attached_files,
        convo=convo,
        conversation_id=str(convo.id),
    )
    if pipeline_resp is not None:
        return pipeline_resp

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

    # Tone resolution order (Lumo-inspired, Ondata α #1):
    #   1. user.tone_preference  (per-user override, NULL = inherit)
    #   2. admin_settings.tone_preset  (family default)
    #   3. "default"  (no overlay)
    # Privacy is admin-only — it strips history + facts, which is a mode
    # we don't expose as a self-service user choice.
    user_tone = getattr(user, "tone_preference", None)
    if user_tone and user_tone in _TONE_DIRECTIVE and user_tone != "privacy":
        tone_preset = user_tone
    else:
        admin_tone = await setting_svc.get(session, "tone_preset")
        tone_preset = admin_tone if admin_tone in _TONE_DIRECTIVE else "default"
    tone_directive = _TONE_DIRECTIVE.get(tone_preset, "")
    if tone_directive:
        sysprompt_active = sysprompt_active + tone_directive

    # RAG: top-k facts for THIS user vs THIS question. Off in privacy
    # mode (the whole point of privacy is to not leak stored facts back
    # into the prompt) and off when the message is empty or only an
    # attachment. Failures are swallowed — retrieval is best-effort and
    # must never break a chat reply.
    if tone_preset != "privacy" and last_user_q and len(last_user_q.strip()) >= 4:
        try:
            from cara.ai.embeddings import EmbeddingService as _EmbeddingService
            from cara.api.v1._chat_system_prompt import build_facts_block
            from cara.learning import semantic as _semantic_mod

            _embedder = _EmbeddingService()
            hits = await _semantic_mod.top_k_for_query(
                session,
                query=last_user_q,
                user_id=user.id,
                embedder=_embedder,
                k=3,
                min_score=0.5,
            )
            if hits:
                facts_block = build_facts_block(
                    [f.text for f, _score in hits],
                    user_name=(user.full_name or user.email.split("@")[0]).split()[0],
                )
                if facts_block:
                    sysprompt_active = f"{sysprompt_active}\n\n{facts_block}"
                logger.info(
                    "chat.rag.facts_injected",
                    user_id=user.id,
                    count=len(hits),
                    top_score=round(hits[0][1], 3),
                )
        except Exception as exc:  # noqa: BLE001 — RAG is best-effort
            logger.warning("chat.rag.failed", error=str(exc))

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

    # If this question is going to trigger the agent loop anyway (the
    # query matches a knowledge-need pattern), keep the first pass *short*
    # so the user doesn't watch the 1.5B confidently invent details for
    # 90+ seconds before the grounded revision overwrites it. 80 tokens
    # is enough for a [TOOL: discover ...] emission or a short hedge but
    # not enough to drift into a fabricated explanation.
    if last_user_q and _needs_grounding(last_user_q):
        effective_max = min(effective_max, 80)

    # Per-conversation KV-cache path. RKLLM persists the prefill state to
    # this file at the end of each run and re-uses it on the next call —
    # turns 2+ skip prefill, dropping TTFT from ~200 ms to ~50 ms.
    # Invalidated when the admin edits the runtime system prompt
    # (cara.ai.kv_cache.flush_one is what the admin handler will call).
    kv_path = kv_cache.path_for_conversation(convo_id_str)

    # Reaching this point means none of the deterministic routing tiers
    # (skill / recipe_chain / intent_router) matched the user message —
    # we're falling through to the full LLM generation. Record a
    # `router.miss` so the reflective batch (Step 8.5) can cluster
    # frequently-missed phrases and propose new intents to the admin.
    if last_user_q:
        await episodic.record_async(
            kind="router.miss",
            user_id=user.id,
            ref_id=convo_id_str,
            outcome="fallthrough",
            payload={"message": last_user_q[:300]},
        )

    # Cloud LLM short-circuit: if the user explicitly opted-in via
    # `prefer_cloud=true` AND the admin flag is on, skip the local model
    # entirely for this turn and stream Anthropic Haiku's reply through
    # the same SSE format. The local conversation history is NOT sent
    # to the cloud — only the last user turn (privacy by truncation).
    cloud_enabled = await setting_svc.get(session, "cloud_llm_enabled")
    use_cloud = bool(req.prefer_cloud and cloud_enabled)
    if use_cloud:
        from cara.services import cloud_llm as _cloud

        if not _cloud.is_available():
            logger.info("chat.cloud_llm.skipped_no_key")
            use_cloud = False

    if use_cloud:
        from cara.services import cloud_llm as _cloud

        async def cloud_stream() -> AsyncIterator[bytes]:
            yield _sse("meta", {"conversation_id": convo_id_str})

            sm = get_state_machine()
            bus = get_bus()
            sm.transition(LumoState.THINKING)
            bus.emit(
                "chat.cloud_llm.start",
                {"user_id": user.id, "user_chars": len(last_user_q or "")},
            )

            t_start_c = time.monotonic()
            t_first_c: float | None = None
            buf_c: list[str] = []
            try:
                async for delta in _cloud.cloud_chat_stream(last_user_q or ""):
                    if t_first_c is None:
                        t_first_c = time.monotonic() - t_start_c
                        sm.transition(LumoState.SPEAKING)
                    buf_c.append(delta)
                    yield _sse("token", {"text": delta, "token_id": -1})
            except _cloud.CloudLLMUnavailable as exc:
                logger.warning("chat.cloud_llm.failed", error=str(exc))
                yield _sse(
                    "error",
                    {"detail": f"Cloud non disponibile: {exc}. Riprova senza prefer_cloud."},
                )
                yield _sse(
                    "done",
                    {
                        "conversation_id": convo_id_str,
                        "tokens": 0,
                        "first_token_seconds": 0.0,
                        "total_seconds": 0.0,
                        "tokens_per_second": 0.0,
                        "routed": "cloud_llm_failed",
                    },
                )
                return

            full_c = "".join(buf_c).strip()
            if full_c and _sessionmaker is not None:
                try:
                    async with _sessionmaker() as s_save:
                        await convo_svc.add_message(
                            s_save,
                            conversation_id=convo.id,
                            role="assistant",
                            content=full_c,
                        )
                        await s_save.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("chat.cloud_llm.save_failed", error=str(exc))

            t_total = time.monotonic() - t_start_c
            ttft = t_first_c if t_first_c is not None else 0.0
            yield _sse(
                "done",
                {
                    "conversation_id": convo_id_str,
                    "tokens": len(buf_c),
                    "first_token_seconds": round(ttft, 3),
                    "total_seconds": round(t_total, 3),
                    "tokens_per_second": round(len(buf_c) / t_total, 2) if t_total > 0 else 0.0,
                    "routed": "cloud_llm",
                },
            )
            sm.transition(LumoState.IDLE)
            bus.emit(
                "chat.cloud_llm.done",
                {
                    "user_id": user.id,
                    "answer_chars": len(full_c),
                    "duration_s": round(t_total, 2),
                },
            )

        return StreamingResponse(
            cloud_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Sentence-streaming TTS: when the admin flag is on, we synthesize
    # each LLM sentence as it forms and ship a base64-encoded WAV chunk
    # alongside the token stream. The frontend audio queue plays them
    # sequentially → user hears the first sentence ~2s after the LLM
    # starts emitting, instead of waiting for the full response.
    tts_streaming_on = bool(
        await setting_svc.get(session, "tts_streaming_enabled")
    )
    tts_voice_id: str | None = None
    if tts_streaming_on:
        tts_voice_id = (
            (await setting_svc.get(session, "voice_name"))
            or settings.tts_default_voice
        )
        # Only Piper voices have server-side synth; browser voices stay client-side.
        if not (tts_voice_id and tts_voice_id.startswith("piper:")):
            tts_streaming_on = False

    async def stream() -> AsyncIterator[bytes]:
        yield _sse("meta", {"conversation_id": convo_id_str})

        sm = get_state_machine()
        bus = get_bus()
        sm.transition(LumoState.THINKING)
        bus.emit(
            "chat.llm.start",
            {"user_id": user.id, "prompt_chars": len(prompt)},
        )

        # Sentence-buffer state local to this request.
        from cara.api.v1._chat_tts_stream import (
            SentenceBuffer as _SentBuf,
            audio_chunk_payload as _audio_chunk_payload,
            synthesize_sentence as _synthesize_sentence,
        )
        sentbuf: _SentBuf | None = _SentBuf() if tts_streaming_on else None
        audio_seq: int = 0

        async def _emit_audio_for(sentence: str):
            nonlocal audio_seq
            if not tts_streaming_on or not sentence.strip():
                return None
            try:
                wav = await _synthesize_sentence(
                    text=sentence, voice_id=tts_voice_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "chat.tts_stream.synth_failed",
                    error=str(exc), preview=sentence[:60],
                )
                return None
            if not wav:
                return None
            payload = _audio_chunk_payload(
                seq=audio_seq, text=sentence,
                audio_bytes=wav, voice_id=tts_voice_id or "",
            )
            audio_seq += 1
            return payload

        t_start = time.monotonic()
        t_first: float | None = None
        n = 0
        buf: list[str] = []
        try:
            async for chunk in llm.generate(
                prompt,
                max_new_tokens=effective_max,
                prompt_cache_path=kv_path,
            ):
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

                # Detect and synthesize each completed sentence on the fly.
                if sentbuf is not None and chunk.text:
                    for sentence in sentbuf.feed(chunk.text):
                        # Strip any leftover [TOOL: ...] tags from the audio
                        # so the user doesn't hear them spoken aloud.
                        clean = re.sub(
                            r"\[\s*(?:[A-Z_]+\s*:?\s*)?[a-z_]+\b[^\]]*?\]",
                            "", sentence,
                        ).strip()
                        if not clean:
                            continue
                        payload = await _emit_audio_for(clean)
                        if payload is not None:
                            yield _sse("audio_chunk", payload)
        except LLMUnavailableError as exc:
            logger.warning("chat.llm_unavailable", error=str(exc))
            yield _sse("error", {"detail": str(exc)})
            return
        except Exception as exc:  # pragma: no cover
            logger.exception("chat.unhandled")
            yield _sse("error", {"detail": f"internal error: {exc!r}"})
            return

        # Flush the trailing tail (a final sentence without terminator).
        if sentbuf is not None:
            for sentence in sentbuf.flush():
                clean = re.sub(
                    r"\[\s*(?:[A-Z_]+\s*:?\s*)?[a-z_]+\b[^\]]*?\]",
                    "", sentence,
                ).strip()
                if not clean:
                    continue
                payload = await _emit_audio_for(clean)
                if payload is not None:
                    yield _sse("audio_chunk", payload)

        t_total = time.monotonic() - t_start
        full_text = "".join(buf)
        # The text we eventually persist + return; may be replaced by the
        # self-critique pass below if validation is on and the verdict is RIVEDI.
        final_text = full_text

        # Episodic memory: one row per chat turn. Fire-and-forget — failures
        # never block the user-visible response. The reflective batch
        # (Step 8.5) clusters these to surface "what's the model failing at?".
        await episodic.record_async(
            kind="chat.turn",
            user_id=user.id,
            outcome="ok",
            duration_ms=t_total * 1000,
            ref_id=convo_id_str,
            payload={
                "tokens": n,
                "first_token_seconds": round(t_first, 3) if t_first else None,
                "tokens_per_sec": round(n / max(t_total, 1e-6), 2),
                "prompt_chars": len(prompt),
                "kv_cache_path": str(kv_path) if kv_path else None,
            },
        )

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

                # If we got actual prose (not just a stream URL or empty), pick
                # the most relevant 1-3 sentences EXTRACTIVELY from the article
                # and quote them verbatim. This avoids the 1.5B's habit of
                # inventing Italian words while "summarising" web content.
                # The LLM second-pass is kept only as a fallback when the
                # extractive output is too short to be useful (e.g. very short
                # article or the article shares no vocabulary with the query).
                if discovered and article_text and len(article_text) > 80 and kind == "article":
                    from cara.services.extractive_summary import summarise_article

                    extractive = summarise_article(
                        article_text,
                        query=last_user,
                        title=discovered.title,
                        max_chars=380,
                    )
                    second_text = ""
                    used_extractive = False

                    if extractive and len(extractive) >= 80:
                        second_text = extractive
                        used_extractive = True
                        logger.info(
                            "chat.agent_loop.extractive.applied",
                            article_chars=len(article_text),
                            extract_chars=len(extractive),
                            source=discovered.source_domain,
                        )
                    else:
                        # Fall back to the LLM second pass only when extraction
                        # didn't yield enough text. Keeps the safety net for
                        # short articles where TextRank-lite degenerates.
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
                            extract_too_short=len(extractive) if extractive else 0,
                            source=discovered.source_domain,
                        )
                        second_buf: list[str] = []
                        try:
                            async for chunk in llm.generate(
                                new_prompt,
                                max_new_tokens=140,
                                prompt_cache_path=kv_path,
                            ):
                                second_buf.append(chunk.text)
                        except LLMUnavailableError as exc:
                            logger.warning(
                                "chat.agent_loop.second_pass.llm_unavailable",
                                error=str(exc),
                            )
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

        # ── Fail-loud policy ─────────────────────────────────────────────
        # CARA must NEVER end a turn silently. Voice users have no other
        # cue: an empty stream looks like a hang. Detect three failure
        # modes and synthesise a helpful fallback before `done`:
        #   (a) zero tokens emitted (RKLLM aborted, prompt edge case)
        #   (b) only `[TOOL: ...]` tags emitted, parser strips to nothing
        #   (c) the 1.5B regurgitated a fragment of the system prompt
        #       (telltale words: "DIRETTAMENTE", "SENZA usare", "tu stesso")
        visible = re.sub(
            r"\[\s*(?:[A-Z_]+\s*:?\s*)?[a-z_]+\b[^\]]*?\]",
            "",
            final_text,
        ).strip()
        garbage_markers = (
            "DIRETTAMENTE", "SENZA usare", "tu stesso", "tu stessa",
            "rispondi con UNA", "[TOOL:", "## TOOL", "## QUANDO",
        )
        is_garbage = any(m in visible for m in garbage_markers)
        # Identity-leak: the LLM defaults to "Sono Cara, l'assistente..."
        # whenever it doesn't know what else to say. That's only a
        # legitimate answer when the user asked "chi sei". For anything
        # else, swap it for the fallback so the user gets actionable help.
        ql_low = (last_user or "").strip().lower()
        is_identity_leak = (
            visible.lower().startswith(("sono cara", "ciao, sono cara"))
            and not any(k in ql_low for k in ("chi sei", "presentati", "come ti chiami", "il tuo nome"))
        )
        if not visible or len(visible) < 4 or is_garbage or is_identity_leak:
            ql = (last_user or "").lower()
            # Tailor the suggestion to the user's apparent intent.
            if any(w in ql for w in (
                "evento", "appuntament", "impegno", "ricordami", "metti", "aggiungi",
            )):
                fallback = (
                    "Scusa, non ho capito esattamente. "
                    "Se vuoi aggiungere un appuntamento prova ad esempio: "
                    "«aggiungi appuntamento dal medico sabato alle 16» "
                    "oppure «ricordami compleanno di Ilaria il 12 maggio»."
                )
            elif any(w in ql for w in (
                "spesa", "compra", "lista",
            )):
                fallback = (
                    "Scusa, non ho capito. "
                    "Per la spesa prova ad esempio: «aggiungi pane alla spesa» "
                    "oppure «mostra la spesa»."
                )
            elif any(w in ql for w in (
                "tempo", "meteo", "previsioni", "pioggia",
            )):
                fallback = (
                    "Scusa, non ho capito. "
                    "Per il meteo prova: «che tempo fa», «meteo domani», "
                    "oppure «meteo a Bologna»."
                )
            else:
                fallback = (
                    "Scusa, non ho capito. "
                    "Puoi ripetere con altre parole? Ad esempio: "
                    "«che ore sono», «aggiungi appuntamento sabato alle 16», "
                    "«lista delle cose da fare», oppure «che tempo fa»."
                )
            logger.warning(
                "chat.silent_response_recovered",
                tokens=n,
                visible_len=len(visible),
                garbage=is_garbage,
                identity_leak=is_identity_leak,
                last_user=(last_user or "")[:120],
            )
            if n == 0:
                # No tokens emitted at all — push the fallback as a fresh
                # token so the frontend has something to render.
                yield _sse("token", {"text": fallback, "token_id": -1})
            else:
                # Some tokens were already streamed (identity-leak,
                # garbage, or tool-only). Use `revision` so the frontend
                # REPLACES the displayed text instead of concatenating.
                yield _sse("revision", {"text": fallback})
            payload = await _emit_audio_for(fallback)
            if payload is not None:
                yield _sse("audio_chunk", payload)
            final_text = fallback
            n = max(n, 1)

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
