"""LifeOps M3 — Routines famiglia (seed esempi).

Le routine famiglia sono Reminder ricorrenti con `delivery_context`
JSON che contiene una sequenza di `actions` da eseguire al fire (TTS
+ playback musica + emozione volto + push schermo specifico).

Esempio di delivery_context per la routine 'sveglia mattutina di Sara':
{
  "actions": [
    {"kind": "tts", "voice_text": "Buongiorno Sara, sono le sette."},
    {"kind": "play_radio", "station": "Radio Capital"},
    {"kind": "face_emotion", "emotion": "happy_warm", "duration_s": 30},
    {"kind": "screen", "room": "camera_sara", "view": "morning_dashboard"}
  ],
  "preferred_room": "camera_sara",
  "fallback_channels": []
}

CLI per creare una routine:
    python -m cara.lifeops.routines_seed wake_sara
    python -m cara.lifeops.routines_seed cena_famiglia
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from cara.config import settings
from cara.models import Reminder, User
from cara.store.db import get_sessionmaker, init_engine


log = structlog.get_logger(__name__)


# ─── Template routine famiglia ──────────────────────────────────────


ROUTINE_TEMPLATES: dict[str, dict[str, Any]] = {
    "wake_sara": {
        "title": "Sveglia mattutina di Sara",
        "category": "famiglia",
        "fires_at_local_time": "07:00",
        "recurrence": "weekly",
        "rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=7;BYMINUTE=0",
        "delivery_context": {
            "actions": [
                {
                    "kind": "tts",
                    "voice_text": "Buongiorno Sara, sono le sette. È ora di prepararsi per la scuola.",
                },
                {"kind": "play_radio", "station": "Radio Capital"},
                {"kind": "face_emotion", "emotion": "happy_warm", "duration_s": 30},
                {
                    "kind": "screen",
                    "room": "camera_sara",
                    "view": "morning_dashboard",
                },
            ],
            "preferred_room": "camera_sara",
            "fallback_channels": [],
        },
    },
    "wake_matteo": {
        "title": "Sveglia mattutina di Matteo",
        "category": "famiglia",
        "fires_at_local_time": "07:15",
        "recurrence": "weekly",
        "rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=7;BYMINUTE=15",
        "delivery_context": {
            "actions": [
                {
                    "kind": "tts",
                    "voice_text": "Buongiorno Matteo, è ora di alzarsi.",
                },
                {"kind": "face_emotion", "emotion": "happy_warm", "duration_s": 20},
            ],
            "preferred_room": "camera_matteo",
        },
    },
    "cena_famiglia": {
        "title": "Cena famiglia",
        "category": "famiglia",
        "fires_at_local_time": "19:30",
        "recurrence": "weekly",
        "rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;BYHOUR=19;BYMINUTE=30",
        "delivery_context": {
            "actions": [
                {"kind": "tts", "voice_text": "È ora di cena. Tutti a tavola!"},
                {"kind": "face_emotion", "emotion": "warm_glow"},
            ],
            "fallback_channels": ["push"],
        },
    },
    "buona_notte_bimbi": {
        "title": "Buonanotte bambini",
        "category": "famiglia",
        "fires_at_local_time": "21:00",
        "recurrence": "weekly",
        "rrule": "FREQ=WEEKLY;BYHOUR=21;BYMINUTE=0",
        "delivery_context": {
            "actions": [
                {
                    "kind": "tts",
                    "voice_text": "Buonanotte Sara, buonanotte Matteo. Sogni d'oro.",
                },
                {"kind": "face_emotion", "emotion": "tender", "duration_s": 60},
                {"kind": "lights", "room": "casa", "scene": "notte"},
            ],
        },
    },
    "promemoria_farmaco": {
        "title": "Farmaco quotidiano",
        "category": "salute",
        "fires_at_local_time": "09:00",
        "recurrence": "weekly",
        "rrule": "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
        "urgent": True,
        "delivery_context": {
            "actions": [
                {"kind": "tts", "voice_text": "Promemoria farmaco delle nove."},
                {"kind": "face_emotion", "emotion": "attentive"},
            ],
            "fallback_channels": ["push", "telegram"],
        },
    },
}


async def create_routine_for_user(user_email: str, template_slug: str) -> int:
    """Crea una routine per l'utente specificato. Idempotente: se esiste
    già un reminder con stesso source='routine' + title, lo aggiorna."""
    # CLI standalone: init engine se non già fatto.
    try:
        sessionmaker = get_sessionmaker()
    except RuntimeError:
        await init_engine()
        sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        # Trova utente
        from sqlalchemy import select  # noqa: PLC0415

        u_stmt = select(User).where(User.email == user_email)
        user = (await session.execute(u_stmt)).scalar_one_or_none()
        if user is None:
            raise ValueError(f"User {user_email} not found")

        if template_slug not in ROUTINE_TEMPLATES:
            raise ValueError(
                f"Template {template_slug} non esiste. "
                f"Disponibili: {list(ROUTINE_TEMPLATES)}"
            )

        tmpl = ROUTINE_TEMPLATES[template_slug]
        # Cerca esistente
        r_stmt = select(Reminder).where(
            Reminder.user_id == user.id,
            Reminder.title == tmpl["title"],
            getattr(Reminder, "source", None) == "routine",
        )
        existing = (await session.execute(r_stmt)).scalar_one_or_none()

        # Calcola due_at iniziale (prossima occorrenza del fires_at_local_time)
        from datetime import time as dtime  # noqa: PLC0415
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        rome = ZoneInfo("Europe/Rome")
        now_rome = datetime.now(rome)
        hh, mm = (int(x) for x in tmpl["fires_at_local_time"].split(":"))
        candidate = now_rome.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now_rome:
            candidate = candidate + timedelta(days=1)
        due_at = candidate.astimezone(timezone.utc)

        if existing:
            existing.delivery_context = tmpl["delivery_context"]
            existing.urgent = tmpl.get("urgent", False)
            existing.due_at = due_at
            log.info("routine.updated", slug=template_slug, user_id=user.id)
            return existing.id

        reminder = Reminder(
            user_id=user.id,
            category=tmpl["category"],
            title=tmpl["title"],
            due_at=due_at,
            recurrence=tmpl["recurrence"],
            lead_times=[],
            status="active",
            source="routine",
            urgent=tmpl.get("urgent", False),
            delivery_context=tmpl["delivery_context"],
        )
        session.add(reminder)
        await session.commit()
        log.info("routine.created", slug=template_slug, user_id=user.id, reminder_id=reminder.id)
        return reminder.id


def _cli() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m cara.lifeops.routines_seed <user_email> <template_slug>")
        print(f"Templates: {list(ROUTINE_TEMPLATES)}")
        sys.exit(1)
    email = sys.argv[1]
    slug = sys.argv[2]
    asyncio.run(create_routine_for_user(email, slug))


if __name__ == "__main__":
    _cli()
