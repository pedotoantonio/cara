"""Telegram bot wrapper for CARA.

Disabled by default. To enable:

  1. Create a bot via @BotFather, copy the API token.
  2. In `/opt/cara/.env` set:
       CARA_TELEGRAM_BOT_TOKEN=<token>
       CARA_TELEGRAM_CHAT_OWNERS=<your_telegram_chat_id>          # comma-separated allow-list
       CARA_TELEGRAM_CHAT_USER_MAP=<chat_id>:<user_email>         # optional explicit binding
  3. `cd /opt/cara && docker compose --profile app restart backend`
  4. Open the bot in Telegram and send /start.

Each authorised chat is auto-bound to the configured owner email (first user
mapped, or the existing owner if there is exactly one user). All chats use the
shared `LLMService` of the backend process; concurrency is serialised by the
service's asyncio lock just like the web client.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import Any

import structlog
from sqlalchemy import select
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from cara.ai import get_llm_service
from cara.ai.llm import LLMUnavailableError
from cara.config import settings
from cara.models import User
from cara.schemas.chat import ChatMessage
from cara.services import conversations as convo_svc
from cara.services import shopping as shop_svc
from cara.services import tasks as task_svc
from cara.store.db import get_sessionmaker

logger = structlog.get_logger(__name__)

# One persistent CARA conversation per Telegram chat.
_chat_to_convo: dict[int, uuid.UUID] = {}


def _parse_owners() -> set[int]:
    raw = settings.cara_telegram_chat_owners
    out: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.add(int(item))
        except ValueError:
            logger.warning("telegram.invalid_owner_chat_id", value=item)
    return out


def _parse_user_map() -> dict[int, str]:
    raw = settings.cara_telegram_chat_user_map
    out: dict[int, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        cid, email = entry.split(":", 1)
        try:
            out[int(cid.strip())] = email.strip().lower()
        except ValueError:
            continue
    return out


_OWNERS = _parse_owners()
_USER_MAP = _parse_user_map()


async def _resolve_user_for_chat(chat_id: int) -> User | None:
    """Map a Telegram chat_id → CARA `User`. Resolution order:
      1. DB row in `telegram_chat_mappings` (admin-managed runtime).
      2. env-var `CARA_TELEGRAM_CHAT_OWNERS` + `…_USER_MAP` bootstrap.
      3. fallback: when there's exactly one user in DB, use it.

    DB mappings imply allowlist (presence of a row = authorised).
    """
    try:
        get_sessionmaker()
    except RuntimeError:
        return None
    from cara.services import telegram_mappings as tg_map  # noqa: PLC0415

    async with get_sessionmaker()() as session:
        # 1. DB mapping wins.
        row = await tg_map.get_by_chat_id(session, chat_id)
        if row is not None:
            user = await session.get(User, row.user_id)
            if user is not None and user.is_active:
                try:
                    await tg_map.touch(session, chat_id)
                    await session.commit()
                except Exception:  # noqa: BLE001
                    await session.rollback()
                return user

        # 2. Env-var bootstrap.
        if chat_id not in _OWNERS:
            return None
        email = _USER_MAP.get(chat_id)
        if email:
            stmt = select(User).where(User.email == email)
            return (await session.execute(stmt)).scalar_one_or_none()

        # 3. Single-user shortcut for personal installs.
        rows = (await session.execute(select(User))).scalars().all()
        return rows[0] if len(rows) == 1 else None


def _qwen_prompt(history: list) -> str:
    parts = []
    for m in history:
        parts.append(f"<|im_start|>{m.role}\n{m.content}<|im_end|>\n")
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


async def _ensure_conversation(chat_id: int, user: User) -> uuid.UUID:
    """Resolve a stable Conversation UUID for this Telegram chat.
    Persisted in `telegram_chat_mappings.conversation_id` so it
    survives backend restarts (and so the admin UI can list "active
    chats with last message at …").
    """
    # Fast path — in-process cache.
    if chat_id in _chat_to_convo:
        return _chat_to_convo[chat_id]

    _ = get_sessionmaker()  # ensure DB engine is up
    from cara.services import telegram_mappings as tg_map  # noqa: PLC0415

    async with get_sessionmaker()() as session:
        # Try the persisted pointer first — but verify the Conversation
        # row still exists. Cascading deletes from `users` (or manual
        # admin cleanups) can leave the mapping pointing at a UUID that
        # no longer exists, which would later trip the messages FK with
        # `ForeignKeyViolationError`. Dangling pointers must be re-bound,
        # not blindly re-used.
        row = await tg_map.get_by_chat_id(session, chat_id)
        if row is not None and row.conversation_id is not None:
            existing = await convo_svc.get_conversation(
                session, row.conversation_id, user_id=user.id,
            )
            if existing is not None:
                _chat_to_convo[chat_id] = row.conversation_id
                return row.conversation_id
            logger.warning(
                "telegram.conversation_orphan",
                chat_id=chat_id,
                stale_conversation_id=str(row.conversation_id),
                user_id=user.id,
            )

        # Create a new conversation + persist back to the mapping row.
        convo = await convo_svc.create_conversation(
            session, user_id=user.id, title=f"Telegram {chat_id}"
        )
        await convo_svc.add_message(
            session, conversation_id=convo.id, role="system",
            content=settings.llm_system_prompt,
        )

        # Auto-create the mapping row if missing (env-bootstrap users
        # don't have a DB row until first message — this fills it).
        if row is None:
            await tg_map.create_or_update(
                session,
                chat_id=chat_id,
                user_id=user.id,
                label=None,
            )
        await tg_map.set_conversation(session, chat_id, convo.id)
        await session.commit()
        _chat_to_convo[chat_id] = convo.id
        return convo.id


async def _generate_reply(user: User, conversation_id: uuid.UUID, user_text: str) -> str:
    """Persist the user turn, run the LLM, persist the assistant turn, return text."""
    _ = get_sessionmaker()  # ensure DB engine is up
    async with get_sessionmaker()() as session:
        await convo_svc.add_message(
            session, conversation_id=conversation_id, role="user", content=user_text
        )
        await session.commit()
        history = await convo_svc.history_for_prompt(session, conversation_id)
    prompt = _qwen_prompt(
        [ChatMessage(role=m.role, content=m.content) for m in history]  # type: ignore[arg-type]
    )

    try:
        llm = get_llm_service()
    except LLMUnavailableError:
        return "Sono offline al momento, riprova tra poco."

    buf: list[str] = []
    async for chunk in llm.generate(prompt):
        buf.append(chunk.text)
    full = "".join(buf).strip()

    if full:
        async with get_sessionmaker()() as s2:
            await convo_svc.add_message(
                s2, conversation_id=conversation_id, role="assistant", content=full
            )
            await s2.commit()

    return full or "(nessuna risposta)"


# --- handlers -------------------------------------------------------------


async def _gate(update: Update) -> User | None:
    """Auth gate. Resolves chat_id → User via DB mapping (admin-managed)
    or env-bootstrap. On miss, replies with an actionable Italian
    message that includes the chat_id, then notifies the admin so they
    can add the mapping with one tap from /admin/telegram.
    """
    chat = update.effective_chat
    if chat is None:
        return None

    # Phase 5 — try the unified resolver first (DB > env > single-user
    # fallback). Returns None for any unknown / unauthorized chat.
    user = await _resolve_user_for_chat(chat.id)
    if user is not None:
        return user

    # Unknown / unauthorized chat. Tell THIS user where they stand,
    # then ping the admin with the info they need to add the mapping.
    sender = update.effective_user
    sender_name = "?"
    sender_username = ""
    if sender is not None:
        sender_name = sender.full_name or sender.username or str(sender.id)
        sender_username = f"@{sender.username}" if sender.username else ""

    try:
        await chat.send_message(
            "Ciao 👋\n\n"
            "Non sei ancora autorizzato a usare CARA da questa chat.\n"
            f"Il tuo chat_id Telegram è <code>{chat.id}</code>.\n\n"
            "Comunica questo numero a chi gestisce CARA in casa: dovrà "
            "aggiungerti dalla sezione "
            "<a href=\"https://cara.home.lan:8455/admin/telegram\">"
            "Telegram → Aggiungi chat</a> usando il tuo chat_id e la tua "
            "email CARA. Una volta fatto, scrivi di nuovo qui e CARA "
            "ti riconoscerà.",
            parse_mode="HTML", disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.gate.user_message_failed", error=str(exc))

    # Notify the admin via the dispatcher so they get one push +
    # Telegram message with a button to add the chat in one tap.
    try:
        from cara.services.notify import (  # noqa: PLC0415
            Notification, TelegramAction, dispatch,
        )
        await dispatch(
            Notification(
                kind="telegram.unknown_chat",
                title="🔔 Nuovo chat Telegram",
                body=(
                    f"{sender_name} {sender_username} (chat_id "
                    f"<code>{chat.id}</code>) ha scritto al bot. "
                    "Aggiungilo dalla pagina admin se è qualcuno che conosci."
                ),
                tag=f"telegram.unknown_chat.{chat.id}",
                deep_link="/admin/telegram",
                severity="warn",
                extra={"chat_id": chat.id, "sender": sender_name},
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.gate.admin_notify_failed", error=str(exc))

    return None


async def _on_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _gate(update)
    if user is None:
        return
    name = (user.full_name or user.email).split("@")[0].split()[0]
    await update.effective_chat.send_message(
        f"Ciao {name}, sono CARA 🤖\n\n"
        "Scrivimi qualunque cosa (es. \"che tempo fa\", \"appuntamenti settimana prossima\", "
        "\"aggiungi pane alla spesa\") e ti rispondo come dal web.\n\n"
        "Comandi rapidi: /oggi /domani /spesa /note /meteo /casa /cam /help\n",
    )


async def _on_reset(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _gate(update)
    if user is None:
        return
    chat_id = update.effective_chat.id
    _chat_to_convo.pop(chat_id, None)
    # Drop the DB pointer too so the next message starts a fresh
    # Conversation UUID (with a system-prompt seed message).
    try:
        from cara.services import telegram_mappings as tg_map  # noqa: PLC0415
        _ = get_sessionmaker()  # ensure DB engine is up
        async with get_sessionmaker()() as session:
            await tg_map.clear_conversation(session, chat_id)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.reset.persist_failed", error=str(exc))
    await update.effective_chat.send_message("Conversazione azzerata. Da capo.")


async def _on_lista(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _gate(update)
    if user is None:
        return
    _ = get_sessionmaker()  # ensure DB engine is up
    async with get_sessionmaker()() as session:
        tasks = await task_svc.list_tasks(session, user_id=user.id, include_done=False)
    if not tasks:
        await update.effective_chat.send_message("Tutto fatto, niente in lista 🎉")
        return
    lines = [
        f"• {t.title}" + (f"  ⏰ {t.due_date.strftime('%d/%m %H:%M')}" if t.due_date else "")
        for t in tasks
    ]
    await update.effective_chat.send_message("Da fare:\n" + "\n".join(lines))


async def _on_spesa(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _gate(update)
    if user is None:
        return
    _ = get_sessionmaker()  # ensure DB engine is up
    async with get_sessionmaker()() as session:
        items = await shop_svc.list_items(session, user_id=user.id, include_bought=False)
    if not items:
        await update.effective_chat.send_message("Lista spesa vuota.")
        return
    lines = [f"• {i.title}" + (f" ({i.qty})" if i.qty else "") for i in items]
    await update.effective_chat.send_message("Da comprare:\n" + "\n".join(lines))


async def _on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """User sent a voice note or audio file. Download → Whisper STT
    → route as if it were a text message. Optionally reply with a
    voice note when the admin enabled `chat_voice_reply_enabled`.
    """
    user = await _gate(update)
    if user is None:
        return
    chat = update.effective_chat
    msg = update.effective_message
    voice = msg.voice if msg else None
    audio = msg.audio if msg else None
    obj = voice or audio
    if obj is None:
        return

    await ctx.bot.send_chat_action(chat.id, ChatAction.TYPING)
    try:
        tg_file = await ctx.bot.get_file(obj.file_id)
        blob_bytes = await tg_file.download_as_bytearray()
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.voice.download_failed", error=str(exc))
        await chat.send_message("Non sono riuscita a scaricare il vocale.")
        return

    # Pipe through the existing Whisper ASR service. Telegram voice
    # notes are OGG/Opus, audio files vary; faster-whisper handles
    # both via libsndfile.
    text: str | None = None
    try:
        from cara.services.asr import transcribe_bytes  # noqa: PLC0415
        result = await transcribe_bytes(bytes(blob_bytes), language="it")
        if isinstance(result, dict):
            text = result.get("text")
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.voice.transcribe_failed", error=str(exc))

    if not text or not text.strip():
        await chat.send_message(
            "Non ho capito il vocale. Riprova in un posto silenzioso o "
            "scrivi il messaggio."
        )
        return

    transcription = text.strip()
    # Echo the transcription so the user sees what we heard, then
    # process it through the same pipeline as text messages.
    await chat.send_message(f"🎤 _\"{transcription}\"_", parse_mode="Markdown")

    convo_id = await _ensure_conversation(chat.id, user)
    reply: str | None = None
    try:
        reply = await _pipeline_collect(user, convo_id, transcription)
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.voice.pipeline_failed", error=str(exc))
    if reply is None:
        try:
            reply = await _generate_reply(user, convo_id, transcription)
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.voice.llm_failed", error=str(exc))
            reply = f"Errore: {exc!r}"

    if reply:
        try:
            _ = get_sessionmaker()  # ensure DB engine is up
            async with get_sessionmaker()() as s:
                await convo_svc.add_message(
                    s, conversation_id=convo_id, role="user",
                    content=transcription,
                )
                await convo_svc.add_message(
                    s, conversation_id=convo_id, role="assistant", content=reply,
                )
                await s.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.voice.persist_failed", error=str(exc))

    for i in range(0, len(reply), 4000):
        await chat.send_message(reply[i : i + 4000])

    # Optional voice reply — feature-flagged because most users
    # prefer text. The setting is `chat_voice_reply_enabled` (admin).
    voice_reply = await _setting_bool("chat_voice_reply_enabled", default=False)
    if voice_reply and reply:
        try:
            from cara.integrations.telegram_audio import synth_voice_note  # noqa: PLC0415
            ogg = await synth_voice_note(reply[:600])  # cap so audio stays short
            if ogg:
                await ctx.bot.send_voice(chat_id=chat.id, voice=ogg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.voice.synth_failed", error=str(exc))


async def _setting_bool(key: str, *, default: bool) -> bool:
    """Read an admin_settings boolean; falls back to default on
    missing engine / settings (e.g. when the bot starts before the
    DB is fully initialised)."""
    try:
        from cara.services import admin_settings as _admin  # noqa: PLC0415
        _ = get_sessionmaker()  # ensure DB engine is up
        async with get_sessionmaker()() as s:
            v = await _admin.get(s, key)
        if v is None:
            return default
        return bool(v)
    except Exception:  # noqa: BLE001
        return default


async def _on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _gate(update)
    if user is None:
        return
    chat = update.effective_chat
    text = (update.message.text or "").strip() if update.message else ""
    if not text:
        return

    # Step 0 — camera snapshot intercept. Telegram is the only surface
    # that can deliver an inline image, so handle "fammi vedere la
    # cam 136" / "mostrami l'ingresso" / "foto della camera 194" here
    # before the text Pipeline. On match we ship a photo and return;
    # on miss we fall through to the regular chat path.
    try:
        if await _maybe_handle_camera_request(update, ctx, text):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.camera_intercept_failed", error=str(exc))

    convo_id = await _ensure_conversation(chat.id, user)
    await ctx.bot.send_chat_action(chat.id, ChatAction.TYPING)

    # Step 1 — try the deterministic chat Pipeline (intent router,
    # skills, recipe chain). Same code path as the web chat, so
    # "che tempo fa", "lista delle cose da fare", "appuntamenti
    # settimana prossima", etc. produce identical answers in
    # Telegram and on the HomePage.
    reply: str | None = None
    try:
        reply = await _pipeline_collect(user, convo_id, text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.pipeline_failed", error=str(exc))

    # Step 2 — Pipeline missed (free-form chat, "raccontami una
    # barzelletta", etc.) → fall through to the LLM. Persists the
    # turn in the same Conversation row used by the Pipeline so the
    # multi-turn memory is shared.
    if reply is None:
        try:
            reply = await _generate_reply(user, convo_id, text)
        except Exception as exc:  # pragma: no cover
            logger.exception("telegram.generate_failed")
            reply = f"Errore: {exc!r}"

    # Persist the assistant turn so the next message in the same
    # chat sees it as conversation history. Pipeline canned replies
    # don't write to DB themselves (the streaming path in chat.py
    # does that on the web side), so we do it here.
    if reply:
        try:
            _ = get_sessionmaker()  # ensure DB engine is up
            async with get_sessionmaker()() as s:
                await convo_svc.add_message(
                    s, conversation_id=convo_id, role="user", content=text
                )
                await convo_svc.add_message(
                    s, conversation_id=convo_id, role="assistant", content=reply
                )
                await s.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.persist_failed", error=str(exc))

    # Telegram message cap is 4096 chars — chunk if needed.
    for i in range(0, len(reply), 4000):
        await chat.send_message(reply[i : i + 4000])


async def _pipeline_collect(
    user: User, convo_id: uuid.UUID, text: str,
) -> str | None:
    """Run the chat Pipeline non-streaming, return the assembled text
    or None on miss (caller falls back to LLM)."""
    from cara.api.v1._chat_pipeline import execute_pipeline_collect  # noqa: PLC0415
    from cara.services.conversations import get_conversation  # noqa: PLC0415

    _ = get_sessionmaker()  # ensure DB engine is up
    async with get_sessionmaker()() as session:
        try:
            convo = await get_conversation(session, convo_id, user_id=user.id)
        except Exception:  # noqa: BLE001
            convo = None
        return await execute_pipeline_collect(
            session=session,
            user=user,
            text=text,
            convo=convo,
            conversation_id=str(convo_id),
        )


# ─── Slash command helpers ────────────────────────────────────────────


async def _run_phrase(
    update: Update, phrase: str, *, fallback_llm: bool = False,
) -> None:
    """Translate a slash command into a natural-language phrase and
    run it through the chat Pipeline. The phrases are chosen so the
    intent router catches them deterministically — no LLM needed for
    `/oggi`, `/spesa`, etc. Set `fallback_llm=True` for commands like
    `/help` where a Pipeline miss is unexpected.
    """
    user = await _gate(update)
    if user is None:
        return
    chat = update.effective_chat
    convo_id = await _ensure_conversation(chat.id, user)

    reply = None
    try:
        reply = await _pipeline_collect(user, convo_id, phrase)
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.cmd.pipeline_failed", phrase=phrase, error=str(exc))

    if reply is None and fallback_llm:
        try:
            reply = await _generate_reply(user, convo_id, phrase)
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram.cmd.llm_failed", phrase=phrase, error=str(exc))

    if not reply:
        reply = "Non ho capito, scusa. Riprova con altre parole o usa /help."

    for i in range(0, len(reply), 4000):
        await chat.send_message(reply[i : i + 4000])


# ─── Concrete slash handlers ──────────────────────────────────────────


async def _on_oggi(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_phrase(update, "cosa devo fare oggi")


async def _on_domani(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_phrase(update, "appuntamenti di domani")


async def _on_settimana(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_phrase(update, "appuntamenti settimana prossima")


async def _on_appuntamenti(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_phrase(update, "elencami i miei appuntamenti")


async def _on_meteo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = ctx.args or []
    city = " ".join(args).strip() if args else ""
    phrase = f"che tempo fa a {city}" if city else "che tempo fa"
    await _run_phrase(update, phrase)


async def _on_casa(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_phrase(update, "chi è in casa")


async def _on_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = ctx.args or []
    cat = " ".join(args).strip() if args else ""
    phrase = f"notizie di {cat}" if cat else "leggi le ultime notizie"
    await _run_phrase(update, phrase)


async def _on_spesa_v2(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/spesa` mostra la lista, `/spesa add <X>` aggiunge."""
    args = ctx.args or []
    if args and args[0].lower() in ("add", "aggiungi"):
        item = " ".join(args[1:]).strip()
        if not item:
            await update.effective_chat.send_message(
                "Uso: /spesa add <prodotto>"
            )
            return
        await _run_phrase(update, f"aggiungi {item} alla spesa")
        return
    await _run_phrase(update, "la spesa")


async def _on_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/note` mostra le note, `/note new <testo>` crea una nota."""
    args = ctx.args or []
    if args and args[0].lower() in ("new", "nuova", "add", "aggiungi"):
        body = " ".join(args[1:]).strip()
        if not body:
            await update.effective_chat.send_message(
                "Uso: /note new <testo della nota>"
            )
            return
        await _run_phrase(update, f"salvami una nota: {body}")
        return
    await _run_phrase(update, "dammi le note")


async def _on_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/task <testo>` aggiunge un task. Senza args: lista."""
    args = ctx.args or []
    if not args:
        await _run_phrase(update, "lista delle cose da fare")
        return
    title = " ".join(args).strip()
    await _run_phrase(update, f"ricordami {title}")


async def _resolve_camera_id(query: str) -> tuple[str | None, str | None]:
    """Resolve a free-form camera reference to a Frigate camera id.

    Accepts:
      - exact id (`cam_194`, `cam_136`) → returned as-is
      - bare number (`136`, `194`) → mapped to `cam_<N>`
      - admin override label (`ingresso`, `cucina`) → looked up in
        `admin_settings["cameras"]`
    Returns (camera_id, label) or (None, None) when the query doesn't
    match any known camera.
    """
    q = query.strip().lower()
    if not q:
        return None, None

    # Pull the live camera list from Frigate via the cameras service so
    # admin overrides + Frigate config stay in sync.
    try:
        from cara.services import cameras as cam_svc  # noqa: PLC0415
        async with get_sessionmaker()() as session:
            cams = await cam_svc.list_cameras(session)
    except Exception:  # noqa: BLE001
        cams = []

    if not cams:
        # Fallback: bare-number heuristic so we still answer when
        # the cameras service is degraded.
        if q.isdigit():
            return f"cam_{q}", None
        if q.startswith("cam_") or q.startswith("cam"):
            return q.replace(" ", "_"), None
        return None, None

    # Exact id match.
    for c in cams:
        if c.id.lower() == q:
            return c.id, c.label
    # Number suffix match: "136" → cam_136
    if q.isdigit():
        for c in cams:
            if c.id.lower().endswith(f"_{q}") or c.id.lower() == f"cam_{q}":
                return c.id, c.label
    # Label / area match: "ingresso" → cam_194 (override)
    for c in cams:
        if (c.label or "").lower() == q or (c.area or "").lower() == q:
            return c.id, c.label
    # Substring fallback (last resort).
    for c in cams:
        if q in c.id.lower() or q in (c.label or "").lower():
            return c.id, c.label
    return None, None


async def _send_camera_snapshot(
    chat, ctx: ContextTypes.DEFAULT_TYPE, cam_id: str, label: str | None = None,
) -> None:
    """Fetch a JPEG from Frigate and ship it via send_photo."""
    import httpx  # noqa: PLC0415

    base = (settings.frigate_url or "").rstrip("/")
    if not base:
        await chat.send_message("Frigate non configurato.")
        return
    url = f"{base}/api/{cam_id}/latest.jpg?h=480"
    try:
        await ctx.bot.send_chat_action(chat.id, ChatAction.UPLOAD_PHOTO)
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(url)
            r.raise_for_status()
            blob = r.content
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.cam_fetch_failed", cam_id=cam_id, error=str(exc))
        await chat.send_message(
            f"Non riesco a leggere la camera {label or cam_id}: {exc}"
        )
        return
    caption = f"📷 {label} ({cam_id})" if label else f"📷 {cam_id}"
    await chat.send_photo(photo=blob, caption=caption)


async def _on_cam(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/cam <id>` scarica lo snapshot da Frigate e lo manda inline.
    Accetta sia l'id (`/cam cam_194`) che il numero (`/cam 194`) che
    la label admin (`/cam ingresso`)."""
    user = await _gate(update)
    if user is None:
        return
    chat = update.effective_chat
    args = ctx.args or []
    if not args:
        await chat.send_message(
            "Uso: /cam <id>  (es. /cam cam_194 oppure /cam ingresso)\n"
            "Usa /casa per vedere chi è in casa."
        )
        return
    raw = " ".join(args).strip()
    cam_id, label = await _resolve_camera_id(raw)
    if cam_id is None:
        await chat.send_message(
            f"Non trovo una camera che corrisponda a \"{raw}\".\n"
            "Camere disponibili: cam_002, cam_020, cam_136, cam_194 (Ingresso)."
        )
        return
    await _send_camera_snapshot(chat, ctx, cam_id, label)


# Free-text patterns that should be intercepted BEFORE the chat
# Pipeline. Camera snapshot requests aren't deterministic intents —
# they're a Telegram-only side channel because the web chat doesn't
# render images inline yet.
#
# Strategy: a small list of "header + tail" regexes, each producing
# a `target` group. Headers cover imperative ("fammi vedere",
# "mostrami", "voglio vedere"), question ("cosa si vede"), bare
# noun ("camera"/"cam"/"telecamera"). Tails cover the optional
# "un'immagine/foto/snapshot della" filler before the target.
import re as _re_cam  # noqa: E402

# Filler tokens that may appear between the verb and the target.
# Italian elision matters: "un'immagine" / "l'immagine" have NO space
# between article and noun, so the article+noun is one combined token
# with whitespace OR apostrophe as separator. Articles standalone
# (without elision) keep the trailing whitespace.
_CAM_FILLER = (
    # Article + photo-like noun. Either "un'immagine" (apostrophe) or
    # "una foto" / "il video" (whitespace separated). Whole group optional.
    r"(?:\s+(?:un['’]|l['’]|un\s+|una\s+|uno\s+|la\s+|il\s+|le\s+|gli\s+|i\s+))?"
    r"(?:foto|immagin[ei]|istantanea|snapshot|inquadratura|panoramica|riprese|ripresa|video|live|stream)?"
    r"(?:\s+(?:di|del|della|dell['’]|sulla|su|dalla|da|in))?"  # prep
    r"(?:\s+(?:la|il|le|gli|i))?"               # second article ("della cam" / "del la cam")
    r"(?:\s+(?:cam(?:era)?|telecamera))?"
    r"(?:\s+(?:numero|n\.))?"
)
_CAM_TARGET = r"\s+(?P<target>[a-zA-Z0-9_àèéìòù]+)\s*[?!.]*$"

_CAMERA_PATTERNS: tuple = tuple(
    _re_cam.compile(rf"^\s*(?:cara,?\s*)?{header}{_CAM_FILLER}{_CAM_TARGET}", _re_cam.IGNORECASE)
    for header in (
        # imperative verbs
        r"fammi\s+vedere",
        r"mostra(?:mi|ci)?",
        r"fai\s+vedere",
        r"voglio\s+vedere",
        r"vorrei\s+vedere",
        r"dam[mn]i",
        r"manda(?:mi)?",
        r"inviami",
        # question forms
        r"che\s+(?:si\s+)?vede",
        r"cosa\s+(?:si\s+)?vede",
        r"cosa\s+c['’]?\s*[èe]",
        r"chi\s+(?:c['’]?\s*[èe]|si\s+vede)",
        # noun-only entry: "foto/immagine/snapshot/camera <X>"
        r"foto",
        r"immagine",
        r"istantanea",
        r"snapshot",
        r"cam(?:era)?",
        r"telecamera",
    )
)


async def _maybe_handle_camera_request(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str,
) -> bool:
    """If `text` looks like 'fammi vedere la cam 136', short-circuit
    the Pipeline + LLM path and ship a snapshot. Returns True when the
    handler took ownership, False when the message should be processed
    normally (chat Pipeline, etc.).
    """
    stripped = text.strip()
    target: str | None = None
    for rx in _CAMERA_PATTERNS:
        m = rx.match(stripped)
        if m is not None:
            target = m.group("target")
            break
    if not target:
        return False
    chat = update.effective_chat
    cam_id, label = await _resolve_camera_id(target)
    if cam_id is None:
        # Don't claim the message — let the chat Pipeline / LLM try.
        return False
    await _send_camera_snapshot(chat, ctx, cam_id, label)
    return True


async def _on_diag(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin only — health check + last-N agent runs in one message."""
    user = await _gate(update)
    if user is None or not user.is_admin:
        if user is not None:
            await update.effective_chat.send_message("Solo admin.")
        return
    chat = update.effective_chat

    lines = ["🩺 <b>CARA diagnostics</b>"]
    try:
        from cara.services import diagnostics as diag_svc  # noqa: PLC0415
        checks = await diag_svc.run_all()
        ok = sum(1 for c in checks if c["status"] == "ok")
        warn = sum(1 for c in checks if c["status"] == "warn")
        err = sum(1 for c in checks if c["status"] == "error")
        lines.append(f"summary: ok={ok} warn={warn} error={err}")
        for c in checks[:12]:
            icon = "✓" if c["status"] == "ok" else ("⚠" if c["status"] == "warn" else "✗")
            lines.append(f"{icon} <b>{c['name']}</b>: {c.get('detail', '')}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"⚠ impossibile leggere diagnostics: {exc}")

    text = "\n".join(lines)
    await chat.send_message(text=text[:4000], parse_mode="HTML")


async def _on_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _gate(update)
    if user is None:
        return
    text = (
        "🤖 <b>Comandi CARA</b>\n\n"
        "📅 <b>Tempo / appuntamenti</b>\n"
        "/oggi — cosa devo fare oggi\n"
        "/domani — appuntamenti di domani\n"
        "/settimana — appuntamenti settimana prossima\n"
        "/appuntamenti — tutti i miei appuntamenti\n\n"
        "🛒 <b>Liste</b>\n"
        "/spesa — lista della spesa\n"
        "/spesa add &lt;prodotto&gt;\n"
        "/note — le mie note\n"
        "/note new &lt;testo&gt;\n"
        "/task — lista task\n"
        "/task &lt;descrizione&gt; — nuovo task\n\n"
        "🌤️ <b>Casa</b>\n"
        "/meteo [città] — meteo (Ferrara di default)\n"
        "/casa — chi è in casa\n"
        "/cam &lt;id&gt; — foto camera (es. /cam cam_194)\n\n"
        "💬 <b>Chat libera</b>\n"
        "Scrivimi qualsiasi cosa — userò CARA come dal web\n\n"
        "🛠️ <b>Sistema</b>\n"
        "/reset — nuova conversazione\n"
        + ("/diag — diagnostica (admin)\n" if user.is_admin else "")
    )
    await update.effective_chat.send_message(text=text, parse_mode="HTML")


# --- inline-keyboard callback dispatch ------------------------------------
#
# Notifications carry actions encoded as `namespace:verb:arg1:arg2...`
# (Telegram caps callback_data at 64 bytes; numeric IDs only). When the
# user taps a button we route to the matching handler, run the action,
# and edit the original message to reflect the new state so the chat
# history stays useful as a log.


async def _ack(query) -> None:  # type: ignore[no-untyped-def]
    """Telegram requires every callback_query be answered within 15s
    or the loading spinner stays forever. Always call this first."""
    try:
        await query.answer()
    except Exception:  # noqa: BLE001
        pass


async def _edit_resolved(query, suffix: str) -> None:  # type: ignore[no-untyped-def]
    """Replace the original message text with `<original> + suffix` and
    drop the keyboard so the buttons can't be tapped twice."""
    try:
        original = (query.message.text or query.message.caption or "").strip()
        new_text = f"{original}\n\n<i>{suffix}</i>"[:4000]
        if query.message.text is not None:
            await query.message.edit_text(
                text=new_text, parse_mode="HTML", reply_markup=None,
                disable_web_page_preview=True,
            )
        else:
            await query.message.edit_caption(
                caption=new_text, parse_mode="HTML", reply_markup=None,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.callback.edit_failed", error=str(exc))


async def _cb_presence_ignore(query, args: list[str]) -> None:  # type: ignore[no-untyped-def]
    if not args:
        await _edit_resolved(query, "⚠ Argomento mancante")
        return
    sighting_id = int(args[0])
    from cara.services import frigate_faces_admin as ff  # noqa: PLC0415
    ok = await ff.ignore_sighting(sighting_id)
    await _edit_resolved(
        query,
        "🚫 Ignorato" if ok else "⚠ Impossibile ignorare (frigate-faces non risponde)",
    )


async def _cb_presence_assign(query, args: list[str]) -> None:  # type: ignore[no-untyped-def]
    if len(args) < 2:
        await _edit_resolved(query, "⚠ Argomenti mancanti")
        return
    sighting_id = int(args[0])
    person_id = int(args[1])
    from cara.services import frigate_faces_admin as ff  # noqa: PLC0415
    person = await ff.get_person(person_id)
    name = (person or {}).get("name") if person else None
    if not name:
        await _edit_resolved(query, "⚠ Persona non trovata")
        return
    ok = await ff.identify_sighting_with_name(sighting_id, str(name))
    await _edit_resolved(
        query,
        f"👤 Riconosciuto come <b>{name}</b>" if ok else "⚠ Riconoscimento fallito",
    )


async def _cb_task_done(query, args: list[str]) -> None:  # type: ignore[no-untyped-def]
    if not args:
        await _edit_resolved(query, "⚠ Argomento mancante")
        return
    task_id = int(args[0])
    try:
        from cara.services import tasks as task_svc  # noqa: PLC0415
        _ = get_sessionmaker()  # ensure DB engine is up
        async with get_sessionmaker()() as s:
            # The chat owner is the task owner — assigned via _USER_MAP.
            owner = await _resolve_user_for_chat(query.message.chat.id)
            if owner is None:
                await _edit_resolved(query, "⚠ Utente non riconosciuto")
                return
            t = await task_svc.update_task(s, task_id, user_id=owner.id, done=True)
            await s.commit()
        await _edit_resolved(
            query,
            f"✅ Fatto: {t.title}" if t else "⚠ Task non trovato",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.cb.task_done_failed", error=str(exc))
        await _edit_resolved(query, f"⚠ Errore: {exc}")


async def _cb_shopping_bought(query, args: list[str]) -> None:  # type: ignore[no-untyped-def]
    if not args:
        await _edit_resolved(query, "⚠ Argomento mancante")
        return
    item_id = int(args[0])
    try:
        from cara.services import shopping as shop_svc  # noqa: PLC0415
        _ = get_sessionmaker()  # ensure DB engine is up
        async with get_sessionmaker()() as s:
            owner = await _resolve_user_for_chat(query.message.chat.id)
            if owner is None:
                await _edit_resolved(query, "⚠ Utente non riconosciuto")
                return
            it = await shop_svc.update_item(s, item_id, user_id=owner.id, bought=True)
            await s.commit()
        await _edit_resolved(
            query,
            f"🛒 Preso: {it.title}" if it else "⚠ Articolo non trovato",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram.cb.shopping_bought_failed", error=str(exc))
        await _edit_resolved(query, f"⚠ Errore: {exc}")


CALLBACK_HANDLERS: dict[str, Any] = {
    "presence:ignore": _cb_presence_ignore,
    "presence:assign": _cb_presence_assign,
    "task:done": _cb_task_done,
    "shopping:bought": _cb_shopping_bought,
}


async def _on_callback(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await _ack(query)
    # Auth: only owners can act on inline buttons.
    if query.message.chat.id not in _OWNERS:
        await _edit_resolved(query, "⚠ Non autorizzato")
        return

    parts = query.data.split(":")
    if len(parts) < 2:
        await _edit_resolved(query, "⚠ Callback non valida")
        return
    key = f"{parts[0]}:{parts[1]}"
    args = parts[2:]
    handler = CALLBACK_HANDLERS.get(key)
    if handler is None:
        logger.warning("telegram.callback.unknown", key=key)
        await _edit_resolved(query, f"⚠ Azione sconosciuta ({key})")
        return
    try:
        await handler(query, args)
    except Exception as exc:  # noqa: BLE001
        logger.exception("telegram.callback.handler_error", key=key)
        await _edit_resolved(query, f"⚠ Errore: {exc}")


# --- lifecycle ------------------------------------------------------------

_application: Application | None = None
_runner_task: asyncio.Task | None = None


async def start_telegram_bot() -> None:
    global _application, _runner_task
    if not settings.cara_telegram_bot_token:
        logger.info("telegram.disabled")
        return
    if not _OWNERS:
        logger.warning("telegram.no_owners_configured", hint="CARA_TELEGRAM_CHAT_OWNERS missing")
        return

    app = (
        ApplicationBuilder()
        .token(settings.cara_telegram_bot_token)
        .build()
    )
    app.add_handler(CommandHandler("start", _on_start))
    app.add_handler(CommandHandler("reset", _on_reset))
    app.add_handler(CommandHandler("help", _on_help))
    # Phase 2 slash commands — all delegate to the chat Pipeline so
    # the bot stays in lockstep with the web HomePage's intent router.
    app.add_handler(CommandHandler("oggi", _on_oggi))
    app.add_handler(CommandHandler("domani", _on_domani))
    app.add_handler(CommandHandler("settimana", _on_settimana))
    app.add_handler(CommandHandler("appuntamenti", _on_appuntamenti))
    app.add_handler(CommandHandler("meteo", _on_meteo))
    app.add_handler(CommandHandler("casa", _on_casa))
    app.add_handler(CommandHandler("news", _on_news))
    app.add_handler(CommandHandler(["spesa", "lista"], _on_spesa_v2))
    app.add_handler(CommandHandler(["note", "nota"], _on_note))
    app.add_handler(CommandHandler(["task", "tasks"], _on_task))
    app.add_handler(CommandHandler("cam", _on_cam))
    app.add_handler(CommandHandler("diag", _on_diag))
    # Phase 3 — voice in / audio in: any voice note or audio file
    # gets transcribed by Whisper and routed as text.
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, _on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
    # Phase 4 — inline keyboard callbacks (presence:assign / ignore,
    # task:done, shopping:bought, …).
    app.add_handler(CallbackQueryHandler(_on_callback))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()  # type: ignore[union-attr]
    _application = app
    logger.info("telegram.started", owners=list(_OWNERS))

    # Keep the polling alive; suppression on shutdown.
    async def _idle() -> None:
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass

    _runner_task = asyncio.create_task(_idle())


async def stop_telegram_bot() -> None:
    global _application, _runner_task
    if _runner_task is not None:
        _runner_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _runner_task
        _runner_task = None
    if _application is not None:
        with contextlib.suppress(Exception):
            await _application.updater.stop()  # type: ignore[union-attr]
            await _application.stop()
            await _application.shutdown()
        _application = None
        logger.info("telegram.stopped")


async def send_message_to_owners(
    text: str,
    *,
    parse_mode: str | None = "Markdown",
    image_url: str | None = None,
    voice_ogg: bytes | None = None,
    keyboard_rows: list[list[dict[str, str]]] | None = None,
) -> None:
    """Push a message (and optional photo / voice note / inline buttons)
    to every chat in `CARA_TELEGRAM_CHAT_OWNERS`.

    `keyboard_rows` is a list of rows; each row a list of
    `{"label": str, "callback_data": str}` dicts. Used by
    `cara.services.notify` to attach actionable buttons to presence
    sightings, task reminders, etc.

    Failures on individual chats are logged and skipped — one
    unreachable owner doesn't block the others.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup  # noqa: PLC0415

    if _application is None:
        logger.debug("telegram.send_message.skipped_no_bot")
        return
    if not _OWNERS:
        logger.debug("telegram.send_message.skipped_no_owners")
        return

    reply_markup = None
    if keyboard_rows:
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=str(b.get("label", "")),
                        callback_data=str(b.get("callback_data", ""))[:64],
                    )
                    for b in row
                ]
                for row in keyboard_rows
                if row
            ]
        )

    bot = _application.bot
    photo_blob: bytes | None = None
    if image_url:
        # Telegram servers cannot reach LAN/docker-internal hosts
        # (e.g. http://frigate-faces:5051/...) — fetch the bytes here
        # and upload them inline. python-telegram-bot v22 also rejects
        # such URLs client-side with "Wrong http url specified".
        import httpx  # noqa: PLC0415
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(image_url)
                r.raise_for_status()
                photo_blob = r.content
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telegram.image_fetch_failed",
                image_url=image_url[:120], error=str(exc),
            )
            photo_blob = None

    for chat_id in _OWNERS:
        try:
            if photo_blob:
                from telegram import InputFile  # noqa: PLC0415
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo_blob, filename="photo.jpg"),
                    caption=text[:1000], parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            else:
                await bot.send_message(
                    chat_id=chat_id, text=text[:4000],
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
            if voice_ogg:
                # A voice note follows the text message so the user
                # sees the headline first then has the audio for
                # eyes-free listening.
                await bot.send_voice(chat_id=chat_id, voice=voice_ogg)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telegram.send_message.failed",
                chat_id=chat_id, error=str(exc),
            )


__all__: list[str] = [
    "start_telegram_bot",
    "stop_telegram_bot",
    "send_message_to_owners",
]


def _hint_unused(_: Any) -> None:  # keeps lint happy on optional deps
    pass
