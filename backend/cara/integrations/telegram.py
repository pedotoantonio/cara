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
    await update.effective_chat.send_message(
        f"Ciao {user.full_name or user.email}! Sono CARA. Scrivimi quello che vuoi.\n\n"
        "Comandi:\n"
        "/lista — le tue cose da fare\n"
        "/spesa — la lista della spesa\n"
        "/reset — inizia una nuova chat",
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
    try:
        reply = await _generate_reply(user, convo_id, text)
    except Exception as exc:  # pragma: no cover
        logger.exception("telegram.generate_failed")
        reply = f"Errore: {exc!r}"
    # Telegram message cap is 4096 chars — chunk if needed.
    for i in range(0, len(reply), 4000):
        await chat.send_message(reply[i : i + 4000])


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
    app.add_handler(CommandHandler("lista", _on_lista))
    app.add_handler(CommandHandler("spesa", _on_spesa))
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


__all__: list[str] = ["start_telegram_bot", "stop_telegram_bot"]


def _hint_unused(_: Any) -> None:  # keeps lint happy on optional deps
    pass
