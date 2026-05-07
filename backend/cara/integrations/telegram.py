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
from cara.store.db import _sessionmaker

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
    if _sessionmaker is None:
        return None
    if chat_id not in _OWNERS:
        return None
    async with _sessionmaker() as session:
        # Explicit chat→user mapping wins
        email = _USER_MAP.get(chat_id)
        if email:
            stmt = select(User).where(User.email == email)
            return (await session.execute(stmt)).scalar_one_or_none()
        # Fallback: if there's exactly one user, use it
        rows = (await session.execute(select(User))).scalars().all()
        return rows[0] if len(rows) == 1 else None


def _qwen_prompt(history: list) -> str:
    parts = []
    for m in history:
        parts.append(f"<|im_start|>{m.role}\n{m.content}<|im_end|>\n")
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


async def _ensure_conversation(chat_id: int, user: User) -> uuid.UUID:
    if chat_id in _chat_to_convo:
        return _chat_to_convo[chat_id]
    assert _sessionmaker is not None  # noqa: S101
    async with _sessionmaker() as session:
        convo = await convo_svc.create_conversation(
            session, user_id=user.id, title=f"Telegram {chat_id}"
        )
        await convo_svc.add_message(
            session, conversation_id=convo.id, role="system",
            content=settings.llm_system_prompt,
        )
        await session.commit()
        _chat_to_convo[chat_id] = convo.id
        return convo.id


async def _generate_reply(user: User, conversation_id: uuid.UUID, user_text: str) -> str:
    """Persist the user turn, run the LLM, persist the assistant turn, return text."""
    assert _sessionmaker is not None  # noqa: S101
    async with _sessionmaker() as session:
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
        async with _sessionmaker() as s2:
            await convo_svc.add_message(
                s2, conversation_id=conversation_id, role="assistant", content=full
            )
            await s2.commit()

    return full or "(nessuna risposta)"


# --- handlers -------------------------------------------------------------


async def _gate(update: Update) -> User | None:
    chat = update.effective_chat
    if chat is None or chat.id not in _OWNERS:
        if chat is not None:
            await chat.send_message("Non sei autorizzato a usare questo bot.")
        return None
    user = await _resolve_user_for_chat(chat.id)
    if user is None:
        await chat.send_message(
            "Bot configurato ma manca il mapping chat→utente CARA. "
            "Imposta CARA_TELEGRAM_CHAT_USER_MAP."
        )
        return None
    return user


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
    await update.effective_chat.send_message("Conversazione azzerata. Da capo.")


async def _on_lista(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _gate(update)
    if user is None:
        return
    assert _sessionmaker is not None  # noqa: S101
    async with _sessionmaker() as session:
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
    assert _sessionmaker is not None  # noqa: S101
    async with _sessionmaker() as session:
        items = await shop_svc.list_items(session, user_id=user.id, include_bought=False)
    if not items:
        await update.effective_chat.send_message("Lista spesa vuota.")
        return
    lines = [f"• {i.title}" + (f" ({i.qty})" if i.qty else "") for i in items]
    await update.effective_chat.send_message("Da comprare:\n" + "\n".join(lines))


async def _on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _gate(update)
    if user is None:
        return
    chat = update.effective_chat
    text = (update.message.text or "").strip() if update.message else ""
    if not text:
        return
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
            assert _sessionmaker is not None  # noqa: S101
            async with _sessionmaker() as s:
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

    assert _sessionmaker is not None  # noqa: S101
    async with _sessionmaker() as session:
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


async def _on_cam(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """`/cam <id>` scarica lo snapshot da Frigate e lo manda inline."""
    user = await _gate(update)
    if user is None:
        return
    chat = update.effective_chat
    args = ctx.args or []
    if not args:
        await chat.send_message(
            "Uso: /cam <id>  (es. /cam cam_194)\n"
            "Usa /casa per vedere chi è in casa o l'app per la lista."
        )
        return
    cam_id = args[0].strip()

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
        await chat.send_message(f"Non riesco a leggere {cam_id}: {exc}")
        return
    await chat.send_photo(photo=blob, caption=f"📷 {cam_id}")


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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))

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
) -> None:
    """Push a message (and optional photo) to every chat in
    `CARA_TELEGRAM_CHAT_OWNERS`. Used by `cara.services.notify` for
    presence alerts, agent failures, proactivity nudges, etc.

    Failures on individual chats are logged and skipped — one
    unreachable owner doesn't block the others.
    """
    if _application is None:
        logger.debug("telegram.send_message.skipped_no_bot")
        return
    if not _OWNERS:
        logger.debug("telegram.send_message.skipped_no_owners")
        return

    bot = _application.bot
    for chat_id in _OWNERS:
        try:
            if image_url:
                await bot.send_photo(
                    chat_id=chat_id, photo=image_url,
                    caption=text[:1000], parse_mode=parse_mode,
                )
            else:
                await bot.send_message(
                    chat_id=chat_id, text=text[:4000],
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
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
