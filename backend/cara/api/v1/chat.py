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
from cara.config import settings
from cara.models.user import User
from cara.schemas.chat import ChatMessage, ChatRequest
from cara.services import conversations as convo_svc
from cara.services import files as file_svc
from cara.store import get_session

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["chat"])

_IM_START = "<|im_start|>"
_IM_END = "<|im_end|>"


def _render_qwen_prompt(messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    for m in messages:
        parts.append(f"{_IM_START}{m.role}\n{m.content}{_IM_END}\n")
    parts.append(f"{_IM_START}assistant\n")
    return "".join(parts)


_WEEKDAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MONTHS_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def _runtime_context_message() -> str:
    """Date, time and timezone — injected into the prompt as a system message
    on every turn so the model knows where/when it is.

    Without this, the 1.5B happily anchors to its training-data cutoff
    (e.g. "oggi è il 28 settembre 2023") and refuses date queries on the
    grounds that "non ho accesso alla data corrente".
    """
    now = datetime.now(ZoneInfo("Europe/Rome"))
    return (
        "## CONTESTO RUNTIME (informazioni precise, NON cercare su internet)\n"
        f"Oggi è {_WEEKDAYS_IT[now.weekday()]} {now.day} "
        f"{_MONTHS_IT[now.month - 1]} {now.year}.\n"
        f"Sono le ore {now.hour:02d}:{now.minute:02d}.\n"
        "Sei a casa della famiglia Pedoto, in Italia (fuso orario Europe/Rome).\n"
        "Per domande tipo \"che giorno è oggi\", \"che ora è\", \"in che mese siamo\" "
        "rispondi DIRETTAMENTE usando queste informazioni, SENZA usare il tool discover."
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

    # Backwards-compat: legacy conversations created before the system-prompt
    # seeding may lack one. Inject it at the top of the prompt without persisting.
    if not any(pm.role == "system" for pm in prompt_messages):
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

    # Resolve effective max_new_tokens: explicit request wins; otherwise admin
    # override; otherwise env default.
    if req.max_new_tokens is not None:
        effective_max = req.max_new_tokens
    else:
        admin_max = await setting_svc.get(session, "llm_max_new_tokens")
        effective_max = int(admin_max) if admin_max else settings.llm_max_new_tokens

    async def stream() -> AsyncIterator[bytes]:
        yield _sse("meta", {"conversation_id": convo_id_str})

        t_start = time.monotonic()
        t_first: float | None = None
        n = 0
        buf: list[str] = []
        try:
            async for chunk in llm.generate(prompt, max_new_tokens=effective_max):
                if t_first is None:
                    t_first = time.monotonic() - t_start
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

        # --- self-critique pass (opt-in via admin flag `validation_enabled`) ---
        # Only run on free-form replies (no tool emissions): the tool branch
        # already has structured ground truth via the executed tool.
        if _sessionmaker is not None and full_text and "[" not in full_text:
            async with _sessionmaker() as s_v:
                v_enabled = await setting_svc.get(s_v, "validation_enabled")
                v_prompt = await setting_svc.get_with_env_fallback(
                    s_v, "llm_validation_prompt", settings.llm_validation_prompt
                )
                v_max = await setting_svc.get_with_env_fallback(
                    s_v, "llm_validation_max_tokens", settings.llm_validation_max_tokens
                )
            if v_enabled:
                last_user = next(
                    (m.content for m in reversed(req.messages) if m.role == "user"),
                    "",
                )
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
