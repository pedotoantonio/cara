"""LifeOps Intent → action dispatchers.

Riceve un Intent tipizzato dal `intent_router.route()` e applica
l'effetto sul DB. Ritorna una stringa canned reply che CARA dirà
all'utente come conferma. Niente LLM nel dispatcher: la risposta è
deterministica.

Pattern:
    intent = lifeops.intent_router.route(utterance, ...)
    if intent.kind != 'unsure':
        reply_text = await dispatchers.execute(intent, user, session)
        # → "Aggiunto pomodori alla spesa. ✅"
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decimal import Decimal

from cara.lifeops.intents import (
    FinanceQueryIntent,
    Intent,
    ListAddIntent,
    ListDoneIntent,
    ListQueryIntent,
    ReminderIntent,
    TransactionAddIntent,
    UnsureIntent,
)
from cara.models import (
    LifeopsAccount,
    LifeopsFinanceCategory,
    LifeopsList,
    LifeopsListItem,
    LifeopsPendingApproval,
    LifeopsTransaction,
    Reminder,
    User,
)


log = structlog.get_logger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────


def _is_child_or_teen(user: User) -> bool:
    return getattr(user, "role", "guest") in {"child", "teen"}


async def _find_or_create_list(
    session: AsyncSession, user: User, slug: str
) -> LifeopsList:
    """Trova lista per slug (sia user-scope dell'utente sia family
    visibile). Se non esiste, ne crea una con scope sensato di default."""
    # User-scope propria
    stmt = (
        select(LifeopsList)
        .where(
            LifeopsList.deleted_at.is_(None),
            LifeopsList.slug == slug,
            (LifeopsList.user_id == user.id)
            | (LifeopsList.scope.in_(("family", "shared"))),
        )
        .order_by(LifeopsList.scope.desc())  # family vince su user
        .limit(1)
    )
    found = (await session.execute(stmt)).scalar_one_or_none()
    if found:
        return found

    # Crea
    default_scope = "family" if slug in {"shopping", "spesa"} else "user"
    titles = {
        "shopping": "Spesa",
        "spesa": "Spesa",
        "todo": "Da fare",
        "viaggio": "Viaggio",
        "regali": "Regali",
    }
    title = titles.get(slug, slug.replace("_", " ").capitalize())
    new_list = LifeopsList(
        user_id=user.id, slug=slug, title=title, scope=default_scope
    )
    session.add(new_list)
    await session.flush()
    log.info(
        "lifeops.dispatcher.list_created",
        slug=slug,
        scope=default_scope,
        user_id=user.id,
    )
    return new_list


async def _find_supervisor(session: AsyncSession, requester: User) -> int | None:
    """Primo user con is_supervisor=true diverso dal requester."""
    stmt = (
        select(User)
        .where(
            getattr(User, "is_supervisor", False).is_(True),
            User.is_active.is_(True),
            User.id != requester.id,
        )
        .order_by(User.created_at.asc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    return row.id if row else None


# ─── Handlers per intent ─────────────────────────────────────────────


async def _handle_list_add(
    intent: ListAddIntent, user: User, session: AsyncSession
) -> str:
    parent = await _find_or_create_list(session, user, intent.list_slug)
    needs_approval = _is_child_or_teen(user) and parent.scope in (
        "family",
        "shared",
    )
    new_item = LifeopsListItem(
        list_id=parent.id,
        user_id=user.id,
        title=intent.item,
        qty=intent.qty,
        unit=intent.unit,
        pending_approval=needs_approval,
    )
    session.add(new_item)
    await session.flush()

    if needs_approval:
        sup_id = await _find_supervisor(session, user)
        pending = LifeopsPendingApproval(
            requested_by_user_id=user.id,
            supervisor_user_id=sup_id,
            target_kind="list_item",
            target_id=new_item.id,
            target_payload={
                "list_id": parent.id,
                "list_title": parent.title,
                "item_title": intent.item,
            },
            expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        )
        session.add(pending)
        await session.flush()
        return (
            f"Ho aggiunto «{intent.item}» a {parent.title}, ma serve "
            f"l'approvazione di mamma o papà. ⏳"
        )

    qty_str = ""
    if intent.qty:
        unit = intent.unit or ""
        qty_str = f" ({intent.qty:g}{(' ' + unit) if unit else ''})"
    return f"Aggiunto «{intent.item}»{qty_str} a {parent.title}. ✅"


async def _handle_list_query(
    intent: ListQueryIntent, user: User, session: AsyncSession
) -> str:
    slug = intent.list_slug or "shopping"
    parent = await _find_or_create_list(session, user, slug)
    stmt = (
        select(LifeopsListItem.title)
        .where(
            LifeopsListItem.list_id == parent.id,
            LifeopsListItem.deleted_at.is_(None),
            LifeopsListItem.done.is_(False),
        )
        .order_by(LifeopsListItem.created_at.desc())
        .limit(15)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return f"{parent.title}: niente da segnalare. La lista è vuota."
    if len(rows) <= 5:
        items = "; ".join(rows)
        return f"{parent.title}: {items}."
    head = "; ".join(rows[:5])
    return f"{parent.title}: {head}… e altri {len(rows) - 5}."


async def _handle_list_done(
    intent: ListDoneIntent, user: User, session: AsyncSession
) -> str:
    slug = intent.list_slug
    parent = await _find_or_create_list(session, user, slug)
    # Match case-insensitive su title contains item_substring
    needle = intent.item_substring.lower()
    stmt = (
        select(LifeopsListItem)
        .where(
            LifeopsListItem.list_id == parent.id,
            LifeopsListItem.deleted_at.is_(None),
            LifeopsListItem.done.is_(False),
            func.lower(LifeopsListItem.title).contains(needle),
        )
        .order_by(LifeopsListItem.created_at.asc())
        .limit(1)
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if not item:
        return (
            f"Non trovo «{intent.item_substring}» nella {parent.title}. "
            "Vuoi che ce lo aggiunga?"
        )
    item.done = True
    item.done_at = datetime.now(timezone.utc)
    item.done_by_user_id = user.id
    await session.flush()
    return f"Segnato «{item.title}» come preso. ✅"


async def _handle_reminder(
    intent: ReminderIntent, user: User, session: AsyncSession
) -> str:
    # Reminders existing model: title + due_at + recurrence (yearly/monthly/
    # weekly) + lead_times. Adattiamo i campi dell'intent al modello.
    due_at = intent.fires_at
    recurrence = None
    if intent.rrule:
        if "FREQ=YEARLY" in intent.rrule:
            recurrence = "yearly"
        elif "FREQ=MONTHLY" in intent.rrule:
            recurrence = "monthly"
        elif "FREQ=WEEKLY" in intent.rrule:
            recurrence = "weekly"

    # Default lead times: 24h prima + 2h prima
    lead_times = [1440, 120] if due_at else []

    reminder = Reminder(
        user_id=user.id,
        category="eventi",  # default; potremo migliorare classificazione
        title=intent.title,
        due_at=due_at or datetime.now(timezone.utc) + timedelta(days=7),
        recurrence=recurrence,
        lead_times=lead_times,
        status="active",
        source="conversational",
        urgent=intent.urgent,
    )
    session.add(reminder)
    await session.flush()

    # Format della risposta
    if due_at:
        local = due_at.astimezone()
        when_str = local.strftime("%A %d %B alle %H:%M")
    elif recurrence == "weekly":
        when_str = "ogni settimana"
    elif recurrence == "yearly":
        when_str = "ogni anno"
    elif recurrence == "monthly":
        when_str = "ogni mese"
    else:
        when_str = "(senza data)"
    return f"Promemoria salvato: «{intent.title}» — {when_str}. ✅"


async def _handle_transaction_add(
    intent: TransactionAddIntent, user: User, session: AsyncSession
) -> str:
    """Crea transaction in stato 'pending'. Utente deve confermare via
    UI (no auto-commit). Conferma esplicita = filosofia LifeOps."""
    # Default account: primo cash dell'utente
    stmt = (
        select(LifeopsAccount)
        .where(
            LifeopsAccount.user_id == user.id,
            LifeopsAccount.deleted_at.is_(None),
            LifeopsAccount.archived_at.is_(None),
        )
        .order_by(LifeopsAccount.created_at.asc())
        .limit(1)
    )
    acc = (await session.execute(stmt)).scalar_one_or_none()
    if acc is None:
        acc = LifeopsAccount(
            user_id=user.id, name="Contanti", kind="cash", currency="EUR"
        )
        session.add(acc)
        await session.flush()

    cat_id = None
    if intent.category_slug:
        cat_stmt = select(LifeopsFinanceCategory).where(
            LifeopsFinanceCategory.slug == intent.category_slug,
            LifeopsFinanceCategory.family_id.is_(None),
        )
        cat = (await session.execute(cat_stmt)).scalar_one_or_none()
        if cat:
            cat_id = cat.id

    tx = LifeopsTransaction(
        user_id=user.id,
        account_id=acc.id,
        category_id=cat_id,
        amount=intent.amount,
        direction=intent.direction,
        happened_at=datetime.now(timezone.utc),
        description=intent.description,
        state="pending",  # ← chiave: aspetta conferma UI
    )
    session.add(tx)
    await session.flush()

    sym = "€"
    desc_str = f" per {intent.description}" if intent.description else ""
    direction_word = "spesa" if intent.direction == "expense" else "entrata"
    return (
        f"Ho registrato una {direction_word} di {intent.amount:.2f}{sym}{desc_str}. "
        f"In attesa di conferma — vai a Finance per approvarla. 💰"
    )


_MONTH_IT_TO_NUM = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


async def _handle_finance_query(
    intent: FinanceQueryIntent, user: User, session: AsyncSession
) -> str:
    """Riepilogo finance basato su periodo + categoria + direction."""
    stmt = select(LifeopsTransaction).where(
        LifeopsTransaction.user_id == user.id,
        LifeopsTransaction.state == "confirmed",
        LifeopsTransaction.deleted_at.is_(None),
    )

    # Period filtering
    now = datetime.now(timezone.utc)
    period_label = "in totale"
    if intent.period_hint == "oggi":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = stmt.where(LifeopsTransaction.happened_at >= start)
        period_label = "oggi"
    elif intent.period_hint == "ieri":
        from datetime import timedelta  # noqa: PLC0415
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
        stmt = stmt.where(
            LifeopsTransaction.happened_at >= start,
            LifeopsTransaction.happened_at < end,
        )
        period_label = "ieri"
    elif intent.period_hint == "settimana":
        from datetime import timedelta  # noqa: PLC0415
        start = now - timedelta(days=7)
        stmt = stmt.where(LifeopsTransaction.happened_at >= start)
        period_label = "questa settimana"
    elif intent.period_hint == "mese":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        stmt = stmt.where(LifeopsTransaction.happened_at >= start)
        period_label = "questo mese"
    elif intent.period_hint == "anno":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        stmt = stmt.where(LifeopsTransaction.happened_at >= start)
        period_label = "quest'anno"
    elif intent.period_hint in _MONTH_IT_TO_NUM:
        m_num = _MONTH_IT_TO_NUM[intent.period_hint]
        start = now.replace(month=m_num, day=1, hour=0, minute=0, second=0, microsecond=0)
        from calendar import monthrange  # noqa: PLC0415
        end_day = monthrange(now.year, m_num)[1]
        end = now.replace(month=m_num, day=end_day, hour=23, minute=59)
        stmt = stmt.where(
            LifeopsTransaction.happened_at >= start,
            LifeopsTransaction.happened_at <= end,
        )
        period_label = f"a {intent.period_hint}"

    if intent.direction:
        stmt = stmt.where(LifeopsTransaction.direction == intent.direction)

    if intent.category_slug:
        cat_stmt = select(LifeopsFinanceCategory.id).where(
            LifeopsFinanceCategory.slug == intent.category_slug,
            LifeopsFinanceCategory.family_id.is_(None),
        )
        cat_id = (await session.execute(cat_stmt)).scalar_one_or_none()
        if cat_id:
            stmt = stmt.where(LifeopsTransaction.category_id == cat_id)

    rows = (await session.execute(stmt)).scalars().all()
    total = sum((tx.amount for tx in rows), Decimal("0"))
    count = len(rows)

    if count == 0:
        cat_str = f" in {intent.category_slug}" if intent.category_slug else ""
        return f"Non hai transazioni{cat_str} {period_label}."

    direction_word = (
        "speso" if intent.direction == "expense" else
        "guadagnato" if intent.direction == "income" else
        "movimentato"
    )
    cat_str = f" in {intent.category_slug}" if intent.category_slug else ""
    return (
        f"Hai {direction_word} {total:.2f}€{cat_str} {period_label} "
        f"({count} transazioni)."
    )


# ─── Entrypoint ──────────────────────────────────────────────────────


async def execute(intent: Intent, user: User, session: AsyncSession) -> str | None:
    """Dispatch Intent → handler. Ritorna canned reply o None se l'intent
    è Unsure (caller deve fallback a LLM).

    NB: NON committa la session. Lascia al caller (chat handler) il
    controllo della transazione.
    """
    if isinstance(intent, UnsureIntent):
        return None
    try:
        if isinstance(intent, ListAddIntent):
            return await _handle_list_add(intent, user, session)
        if isinstance(intent, ListQueryIntent):
            return await _handle_list_query(intent, user, session)
        if isinstance(intent, ListDoneIntent):
            return await _handle_list_done(intent, user, session)
        if isinstance(intent, ReminderIntent):
            return await _handle_reminder(intent, user, session)
        if isinstance(intent, TransactionAddIntent):
            return await _handle_transaction_add(intent, user, session)
        if isinstance(intent, FinanceQueryIntent):
            return await _handle_finance_query(intent, user, session)
    except Exception as exc:  # noqa: BLE001 — log + fallback to LLM
        log.warning(
            "lifeops.dispatcher.failed",
            kind=intent.kind,
            error=str(exc),
            user_id=user.id,
        )
        return None
    return None
