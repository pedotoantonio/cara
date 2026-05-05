"""Concrete proactive rules registered at process start.

Three baseline rules ship in this module:

  1. **morning_greeting** — once per day, between 07:00 and 10:00, fires a
     warm "buongiorno" with a one-line summary of the day (X task, Y
     appuntamenti). Cooldown 20h so it never doubles.

  2. **undone_tasks_evening** — once per day, between 19:00 and 22:00,
     reminds about open tasks that were due TODAY but aren't done.
     Cooldown 18h.

  3. **rain_alert** — when the weather adapter reports rain in the next
     3 hours and we haven't reminded in 4h, suggests bringing an
     umbrella. Cooldown 4h.

Each rule reads from the RuleContext (db_session for task counts,
weather adapter for forecast). They return Suggestion objects the
engine surfaces via push notifications + the dashboard widget.

Importing this module registers all three rules via the @rule
decorator. The engine startup must `import cara.services.proactivity.rules`
exactly once.
"""

from __future__ import annotations

import structlog

from cara.services.proactivity.engine import (
    Priority,
    RuleContext,
    Suggestion,
    rule,
)


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 1) Morning greeting — once between 07:00 and 10:00
# ---------------------------------------------------------------------------


@rule(
    "morning_greeting",
    cooldown_hours=20.0,
    description=(
        "Una volta al giorno fra le 7 e le 10 saluta e riassume "
        "task / appuntamenti di oggi."
    ),
)
async def morning_greeting(ctx: RuleContext) -> Suggestion | None:
    h = ctx.now.hour
    if h < 7 or h >= 10:
        return None

    # Count today's tasks + appointments.
    if ctx.db_session is None:
        return Suggestion(
            rule_id="morning_greeting",
            text="Buongiorno! Pronto per iniziare la giornata?",
            priority=Priority.LOW,
        )

    from datetime import timedelta

    from sqlalchemy import select

    from cara.models.task import Task

    today = ctx.now.date()
    tomorrow = today + timedelta(days=1)

    rows = (
        await ctx.db_session.execute(
            select(Task)
            .where(Task.done.is_(False))
            .where(Task.due_date.is_not(None))
        )
    ).scalars().all()

    today_count = sum(
        1 for t in rows
        if t.due_date and ctx.now.tzinfo and
        t.due_date.astimezone(ctx.now.tzinfo).date() == today
    )

    if today_count == 0:
        text = "Buongiorno! Oggi hai la giornata libera, niente di urgente."
        prio = Priority.LOW
    elif today_count == 1:
        text = "Buongiorno! Hai 1 cosa in programma oggi."
        prio = Priority.MEDIUM
    else:
        text = f"Buongiorno! Hai {today_count} cose in programma oggi."
        prio = Priority.MEDIUM

    return Suggestion(
        rule_id="morning_greeting",
        text=text,
        priority=prio,
        action={"deep_link": "/tasks"},
        expires_at=ctx.now.replace(hour=23, minute=59),
    )


# ---------------------------------------------------------------------------
# 2) Undone tasks evening — gentle reminder of open today's
# ---------------------------------------------------------------------------


@rule(
    "undone_tasks_evening",
    cooldown_hours=18.0,
    description=(
        "Tra le 19 e le 22 ricorda quante task di oggi sono ancora aperte."
    ),
)
async def undone_tasks_evening(ctx: RuleContext) -> Suggestion | None:
    h = ctx.now.hour
    if h < 19 or h >= 22:
        return None
    if ctx.db_session is None:
        return None

    from sqlalchemy import select

    from cara.models.task import Task

    today = ctx.now.date()

    rows = (
        await ctx.db_session.execute(
            select(Task)
            .where(Task.done.is_(False))
            .where(Task.due_date.is_not(None))
        )
    ).scalars().all()

    open_today = [
        t for t in rows
        if t.due_date and ctx.now.tzinfo and
        t.due_date.astimezone(ctx.now.tzinfo).date() == today
    ]

    if not open_today:
        return None  # nothing to nag about — yay

    if len(open_today) == 1:
        text = f"Ti ricordo: oggi avevi \"{open_today[0].title}\" da fare."
    else:
        titles = ", ".join(f"\"{t.title}\"" for t in open_today[:3])
        more = f" e altre {len(open_today) - 3}" if len(open_today) > 3 else ""
        text = f"Ti ricordo: oggi hai ancora aperte {titles}{more}."

    return Suggestion(
        rule_id="undone_tasks_evening",
        text=text,
        priority=Priority.MEDIUM,
        action={"deep_link": "/tasks"},
    )


# ---------------------------------------------------------------------------
# 3) Rain alert — bring an umbrella in the next ~3 hours
# ---------------------------------------------------------------------------


@rule(
    "rain_alert",
    cooldown_hours=4.0,
    description=(
        "Se piove fra meno di 3 ore, suggerisce di prendere l'ombrello."
    ),
)
async def rain_alert(ctx: RuleContext) -> Suggestion | None:
    if ctx.weather is None:
        return None

    # Defensive: weather adapters may expose different APIs. We probe
    # the conventional `forecast_next_hours` first; fall back gracefully.
    fn = getattr(ctx.weather, "forecast_next_hours", None)
    if fn is None:
        return None
    try:
        forecast = await fn(hours=3)
    except Exception as exc:  # noqa: BLE001
        log.debug("rain_alert.weather_failed", error=str(exc))
        return None

    if not forecast:
        return None

    # Heuristic: any entry whose `condition` mentions rain OR
    # `precipitation_mm` >= 0.5 triggers.
    rainy = False
    for hour in forecast:
        cond = (hour.get("condition") or "").lower() if isinstance(hour, dict) else ""
        precip = (hour.get("precipitation_mm") if isinstance(hour, dict) else 0.0) or 0.0
        if "rain" in cond or "pioggia" in cond or "temporale" in cond or precip >= 0.5:
            rainy = True
            break
    if not rainy:
        return None

    return Suggestion(
        rule_id="rain_alert",
        text="Sta per piovere nelle prossime ore — meglio l'ombrello.",
        priority=Priority.MEDIUM,
        action={"deep_link": "/weather"},
    )


# ---------------------------------------------------------------------------
# 4) Door open too long — fed by HA state_changed via episodic
# ---------------------------------------------------------------------------


@rule(
    "door_open_long",
    cooldown_hours=1.0,
    description=(
        "Avvisa quando una porta o finestra è rimasta aperta per più di "
        "20 minuti (riscaldamento / sicurezza)."
    ),
)
async def door_open_long(ctx: RuleContext) -> Suggestion | None:
    if ctx.db_session is None:
        return None
    # Rely on episodic events written by the HA WS subscriber. We look at
    # the last 30 min and find any (entity_id) whose latest state is "on"
    # AND has been "on" continuously for ≥20 minutes.
    from datetime import timedelta

    from sqlalchemy import desc, select

    from cara.models.event import Event

    cutoff = ctx.now - timedelta(minutes=30)
    rows = (
        await ctx.db_session.execute(
            select(Event)
            .where(Event.kind == "ha.state_changed")
            .where(Event.ts >= cutoff)
            .order_by(desc(Event.ts))
            .limit(200)
        )
    ).scalars().all()

    if not rows:
        return None

    # Keep first-seen "on" timestamp per entity.
    open_since: dict[str, object] = {}
    last_state: dict[str, str] = {}
    for r in reversed(rows):  # oldest first
        eid = r.ref_id or ""
        if not eid:
            continue
        # Door/window heuristic: HA naming convention `binary_sensor.*_door`,
        # `*_window`, `cover.*`. Stay conservative.
        if not any(k in eid for k in ("door", "window", "porta", "finestra", "cover")):
            continue
        new_st = (r.payload or {}).get("new") if r.payload else None
        if new_st in ("on", "open"):
            open_since.setdefault(eid, r.ts)
            last_state[eid] = "on"
        else:
            # closed event — clear the timer
            open_since.pop(eid, None)
            last_state[eid] = new_st or ""

    twenty_min = timedelta(minutes=20)
    long_open = [
        eid for eid, ts in open_since.items()
        if last_state.get(eid) == "on" and (ctx.now - ts) >= twenty_min
    ]

    if not long_open:
        return None

    eid = long_open[0]
    pretty = eid.split(".", 1)[-1].replace("_", " ").strip()
    return Suggestion(
        rule_id="door_open_long",
        text=f"\"{pretty}\" è aperta da più di 20 minuti.",
        priority=Priority.HIGH,
        action={"deep_link": "/casa", "entity_id": eid},
    )


# ---------------------------------------------------------------------------
# 5) Bedtime routine — gentle nudge to lock up at night
# ---------------------------------------------------------------------------


@rule(
    "bedtime_routine",
    cooldown_hours=20.0,
    description=(
        "Tra le 22:30 e le 23:30 ricorda di chiudere le luci, "
        "verificare le porte e impostare la sveglia."
    ),
)
async def bedtime_routine(ctx: RuleContext) -> Suggestion | None:
    h, m = ctx.now.hour, ctx.now.minute
    in_window = (h == 22 and m >= 30) or (h == 23 and m < 30)
    if not in_window:
        return None
    return Suggestion(
        rule_id="bedtime_routine",
        text="Buona notte. Vuoi che spenga le luci e blocchi la porta?",
        priority=Priority.MEDIUM,
        action={"deep_link": "/casa"},
    )


# ---------------------------------------------------------------------------
# 6) Birthday — auto-celebrate the user's birth_date
# ---------------------------------------------------------------------------


@rule(
    "birthday_today",
    cooldown_hours=23.0,
    description=(
        "Una volta al giorno controlla se è il compleanno di un membro "
        "della famiglia e propone un saluto."
    ),
)
async def birthday_today(ctx: RuleContext) -> list[Suggestion]:
    if ctx.db_session is None:
        return []
    # Only fire after 06:00 — no point waking anyone with a birthday push.
    if ctx.now.hour < 6:
        return []

    from sqlalchemy import select

    from cara.models.user import User

    rows = (
        await ctx.db_session.execute(
            select(User).where(User.is_active.is_(True)).where(User.birth_date.is_not(None))
        )
    ).scalars().all()

    suggestions: list[Suggestion] = []
    today = ctx.now.date()
    for u in rows:
        if u.birth_date is None:
            continue
        bd = u.birth_date
        if bd.month == today.month and bd.day == today.day:
            name = (u.full_name or u.email).split(" ")[0]
            suggestions.append(Suggestion(
                rule_id=f"birthday_today:{u.id}",
                text=f"Oggi è il compleanno di {name}! Buon compleanno 🎂",
                priority=Priority.HIGH,
                target_user_id=u.id,
                action={"deep_link": "/"},
            ))
    return suggestions


# ---------------------------------------------------------------------------
# 7) Saturday shopping review — before going out
# ---------------------------------------------------------------------------


@rule(
    "shopping_review_saturday",
    cooldown_hours=144.0,  # at most once a week
    description=(
        "Sabato mattina (9-12) suggerisce di rivedere la lista della spesa "
        "prima di uscire."
    ),
)
async def shopping_review_saturday(ctx: RuleContext) -> Suggestion | None:
    if ctx.now.weekday() != 5:  # 0=Mon..5=Sat
        return None
    if ctx.now.hour < 9 or ctx.now.hour >= 12:
        return None
    if ctx.db_session is None:
        return None

    from sqlalchemy import select

    from cara.models.shopping import ShoppingItem

    rows = (
        await ctx.db_session.execute(
            select(ShoppingItem).where(ShoppingItem.bought.is_(False))
        )
    ).scalars().all()

    n = len(rows)
    if n == 0:
        return None  # don't nag if list is already empty

    if n == 1:
        text = "Sabato spesa: hai 1 articolo nella lista."
    else:
        text = f"Sabato spesa: hai {n} articoli nella lista."

    return Suggestion(
        rule_id="shopping_review_saturday",
        text=text,
        priority=Priority.MEDIUM,
        action={"deep_link": "/shopping"},
    )


# ---------------------------------------------------------------------------
# 8) Task overdue — gentle nudge after 24h+ overdue
# ---------------------------------------------------------------------------


@rule(
    "task_overdue_24h",
    cooldown_hours=24.0,
    description=(
        "Una volta al giorno avvisa delle task ancora aperte che erano "
        "scadute da almeno 24 ore."
    ),
)
async def task_overdue_24h(ctx: RuleContext) -> Suggestion | None:
    if ctx.db_session is None:
        return None
    # Only fire during waking hours so we don't push at 3am.
    if ctx.now.hour < 9 or ctx.now.hour >= 21:
        return None

    from datetime import timedelta

    from sqlalchemy import select

    from cara.models.task import Task

    cutoff = ctx.now - timedelta(hours=24)
    rows = (
        await ctx.db_session.execute(
            select(Task)
            .where(Task.done.is_(False))
            .where(Task.due_date.is_not(None))
            .where(Task.due_date < cutoff)
        )
    ).scalars().all()

    if not rows:
        return None

    if len(rows) == 1:
        text = f"\"{rows[0].title}\" era da fare ieri — ti aiuto a riprogrammarla?"
    else:
        text = f"Hai {len(rows)} task in ritardo da almeno un giorno."

    return Suggestion(
        rule_id="task_overdue_24h",
        text=text,
        priority=Priority.MEDIUM,
        action={"deep_link": "/tasks"},
    )


# ---------------------------------------------------------------------------
# 9) Budget drift — category spent > 80% of monthly target
# ---------------------------------------------------------------------------


@rule(
    "budget_drift_warning",
    cooldown_hours=72.0,  # max once every 3 days per category
    description=(
        "Se in una categoria di spesa hai superato l'80% del budget "
        "mensile, suggerisce di rivedere il rollup."
    ),
)
async def budget_drift_warning(ctx: RuleContext) -> Suggestion | None:
    if ctx.db_session is None:
        return None

    try:
        from cara.services.budgets import month_rollup
    except Exception as exc:  # noqa: BLE001
        log.debug("budget_drift.import_failed", error=str(exc))
        return None

    try:
        rollup = await month_rollup(
            ctx.db_session, year=ctx.now.year, month=ctx.now.month,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("budget_drift.rollup_failed", error=str(exc))
        return None

    drifters = []
    for cat_row in (rollup.categories if rollup else []):
        target = cat_row.target_cents or 0
        spent = cat_row.spent_cents or 0
        if target <= 0:
            continue
        ratio = spent / target
        if ratio >= 0.80:
            drifters.append((cat_row.category or "?", ratio))

    if not drifters:
        return None

    drifters.sort(key=lambda r: r[1], reverse=True)
    cat, ratio = drifters[0]
    pct = int(ratio * 100)
    return Suggestion(
        rule_id="budget_drift_warning",
        text=f"Budget {cat}: hai usato il {pct}% del mese. Vuoi vedere il dettaglio?",
        priority=Priority.LOW,
        action={"deep_link": "/wallet"},
    )


# ---------------------------------------------------------------------------
# 10) Lights on while no one is home — saving energy
# ---------------------------------------------------------------------------


@rule(
    "lights_on_nobody_home",
    cooldown_hours=2.0,
    description=(
        "Se la presenza famiglia indica casa vuota e ci sono luci accese, "
        "propone di spegnerle."
    ),
)
async def lights_on_nobody_home(ctx: RuleContext) -> Suggestion | None:
    if ctx.smarthome is None or ctx.family is None:
        return None
    # Don't fire at night when "nobody home" is normal (people sleeping).
    if ctx.now.hour < 8 or ctx.now.hour >= 22:
        return None

    # Family presence: expect a list of present user names / count
    try:
        present = await ctx.family.who_is_home() if callable(getattr(ctx.family, "who_is_home", None)) else None
    except Exception as exc:  # noqa: BLE001
        log.debug("lights_on.presence_failed", error=str(exc))
        return None

    if present is None:
        return None
    # Treat empty list / dict.count==0 / int 0 as "nobody"
    if isinstance(present, (list, tuple, set)):
        nobody = len(present) == 0
    elif isinstance(present, dict):
        nobody = (present.get("count", 0) or 0) == 0
    else:
        try:
            nobody = int(present) == 0
        except (TypeError, ValueError):
            return None
    if not nobody:
        return None

    # Smart-home: count entities domain=light state=on
    try:
        entities = await ctx.smarthome.list_entities()
    except Exception as exc:  # noqa: BLE001
        log.debug("lights_on.smarthome_failed", error=str(exc))
        return None

    on_lights = [
        e for e in (entities or [])
        if getattr(e, "domain", "") == "light"
        and (getattr(e, "state", "") or "").lower() == "on"
    ]
    if not on_lights:
        return None

    if len(on_lights) == 1:
        nice = getattr(on_lights[0], "friendly_name", None) or on_lights[0].id
        text = f"Casa vuota e \"{nice}\" è ancora accesa. Vuoi che la spenga?"
    else:
        text = f"Casa vuota e ci sono {len(on_lights)} luci accese. Vuoi che le spenga?"
    return Suggestion(
        rule_id="lights_on_nobody_home",
        text=text,
        priority=Priority.HIGH,
        action={"deep_link": "/casa", "tool": "lights_off_all"},
    )


# ---------------------------------------------------------------------------
# Convenience: register count + diagnostic
# ---------------------------------------------------------------------------


def registered_rule_ids() -> tuple[str, ...]:
    """Return the IDs the rules in this module register on import."""
    return (
        "morning_greeting",
        "undone_tasks_evening",
        "rain_alert",
        "door_open_long",
        "bedtime_routine",
        "birthday_today",
        "shopping_review_saturday",
        "task_overdue_24h",
        "budget_drift_warning",
        "lights_on_nobody_home",
    )
