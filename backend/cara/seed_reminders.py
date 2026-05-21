"""Seed the `reminder_templates` catalog (idempotent).

Run inside the backend container:

    docker exec cara-backend python -m cara.seed_reminders

Templates are addressed by `slug`; an existing row is updated in
place, missing rows are inserted, no row is ever deleted. Safe to
re-run after iterating on the catalog.

The catalog is intentionally minimal (≥ 14 situations). Adding new
ones is a code change so we keep the user UX consistent — there is
no admin UI to author templates.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cara.config import settings
from cara.models.reminder import ReminderTemplate


log = structlog.get_logger(__name__)


# ─── Field shorthands ─────────────────────────────────────────────


def _f(key: str, label: str, t: str, *, required: bool = False,
       placeholder: str | None = None) -> dict[str, Any]:
    f: dict[str, Any] = {"key": key, "label": label, "type": t, "required": required}
    if placeholder:
        f["placeholder"] = placeholder
    return f


WHO = _f("who", "Per chi", "family_picker", required=True)
DATE_REQ = _f("when", "Quando", "date", required=True)
DATETIME_REQ = _f("when", "Quando", "datetime", required=True)
WHERE = _f("where", "Dove", "text", placeholder="Es. Ospedale S. Anna, Dr. Bianchi")
NOTES = _f("notes", "Note", "text", placeholder="Dettagli aggiuntivi (facoltativo)")


# ─── Catalog ──────────────────────────────────────────────────────


TEMPLATES: list[dict[str, Any]] = [
    # ─────── Famiglia ───────
    {
        "slug": "birthday", "category": "family", "icon": "🎂",
        "title_it": "Un compleanno",
        "fields": [WHO, DATE_REQ, NOTES],
        "default_lead_times": [10080, 1440],     # 7 giorni + 1 giorno
        "default_recurrence": "yearly",
        "order_in_category": 10,
    },
    {
        "slug": "anniversary", "category": "family", "icon": "💍",
        "title_it": "Un anniversario",
        "fields": [
            _f("who_label", "Di chi", "text", required=True,
               placeholder="Es. Mamma e papà"),
            DATE_REQ, NOTES,
        ],
        "default_lead_times": [10080, 1440],
        "default_recurrence": "yearly",
        "order_in_category": 20,
    },
    {
        "slug": "school_event", "category": "family", "icon": "🎓",
        "title_it": "Evento scuola figlio",
        "fields": [WHO, DATETIME_REQ, WHERE, NOTES],
        "default_lead_times": [1440, 120],       # 24h + 2h
        "default_recurrence": None,
        "order_in_category": 30,
    },
    {
        "slug": "family_call", "category": "family", "icon": "📞",
        "title_it": "Chiamare un parente",
        "fields": [
            _f("who_label", "Chi chiamare", "text", required=True),
            DATETIME_REQ, NOTES,
        ],
        "default_lead_times": [60],
        "default_recurrence": None,
        "order_in_category": 40,
    },

    # ─────── Salute ───────
    {
        "slug": "medical_visit", "category": "health", "icon": "🩺",
        "title_it": "Visita medica prenotata",
        "fields": [WHO, DATETIME_REQ, WHERE, NOTES],
        "default_lead_times": [1440, 120],
        "default_recurrence": None,
        "order_in_category": 10,
    },
    {
        "slug": "blood_test", "category": "health", "icon": "🧪",
        "title_it": "Esame del sangue",
        "fields": [WHO, DATETIME_REQ, WHERE, NOTES],
        "default_lead_times": [1440, 720],       # 24h + 12h (digiuno!)
        "default_recurrence": None,
        "order_in_category": 20,
    },
    {
        "slug": "vaccine", "category": "health", "icon": "💉",
        "title_it": "Vaccino o richiamo",
        "fields": [WHO, DATETIME_REQ, WHERE, NOTES],
        "default_lead_times": [1440, 60],
        "default_recurrence": None,
        "order_in_category": 30,
    },
    {
        "slug": "therapy_start", "category": "health", "icon": "💊",
        "title_it": "Iniziare una terapia",
        "fields": [
            WHO,
            _f("medication", "Cosa", "text", required=True,
               placeholder="Es. Antibiotico ogni 8h"),
            DATETIME_REQ, NOTES,
        ],
        "default_lead_times": [60],
        "default_recurrence": None,
        "order_in_category": 40,
    },
    {
        "slug": "checkup_yearly", "category": "health", "icon": "📋",
        "title_it": "Controllo annuale",
        "fields": [
            WHO,
            _f("kind", "Tipo di controllo", "text", required=True,
               placeholder="Es. Visita oculistica"),
            DATE_REQ, NOTES,
        ],
        "default_lead_times": [10080, 1440],
        "default_recurrence": "yearly",
        "order_in_category": 50,
    },

    # ─────── Documenti ───────
    {
        "slug": "id_card_expiry", "category": "documents", "icon": "🆔",
        "title_it": "Carta d'identità in scadenza",
        "fields": [WHO, DATE_REQ, NOTES],
        "default_lead_times": [86400, 20160, 1440],   # 60g + 14g + 1g (in minuti)
        "default_recurrence": None,
        "order_in_category": 10,
    },
    {
        "slug": "driving_license_expiry", "category": "documents", "icon": "🚗",
        "title_it": "Patente in scadenza",
        "fields": [WHO, DATE_REQ, NOTES],
        "default_lead_times": [86400, 20160, 1440],
        "default_recurrence": None,
        "order_in_category": 20,
    },
    {
        "slug": "passport_expiry", "category": "documents", "icon": "✈️",
        "title_it": "Passaporto in scadenza",
        "fields": [WHO, DATE_REQ, NOTES],
        "default_lead_times": [129600, 43200, 1440],  # 90g + 30g + 1g
        "default_recurrence": None,
        "order_in_category": 30,
    },
    {
        "slug": "car_insurance", "category": "documents", "icon": "🚙",
        "title_it": "Assicurazione / bollo auto",
        "fields": [
            _f("vehicle", "Veicolo", "text", required=True,
               placeholder="Es. Fiat 500 targa AB123CD"),
            DATE_REQ, NOTES,
        ],
        "default_lead_times": [43200, 10080, 1440],   # 30g + 7g + 1g
        "default_recurrence": "yearly",
        "order_in_category": 40,
    },
    {
        "slug": "isee_renewal", "category": "documents", "icon": "📋",
        "title_it": "Rinnovo ISEE / certificato",
        "fields": [
            _f("kind", "Tipo certificato", "text", required=True,
               placeholder="Es. ISEE, residenza, casellario"),
            DATE_REQ, NOTES,
        ],
        "default_lead_times": [43200, 10080],
        "default_recurrence": None,
        "order_in_category": 50,
    },

    # ─────── Eventi personali ───────
    {
        "slug": "concert_show", "category": "events", "icon": "🎫",
        "title_it": "Spettacolo o concerto",
        "fields": [
            _f("title", "Cosa", "text", required=True,
               placeholder="Es. Concerto Vasco - Stadio Bologna"),
            DATETIME_REQ, WHERE, NOTES,
        ],
        "default_lead_times": [1440, 120],
        "default_recurrence": None,
        "order_in_category": 10,
    },
    {
        "slug": "travel_departure", "category": "events", "icon": "🧳",
        "title_it": "Partenza viaggio",
        "fields": [
            _f("destination", "Destinazione", "text", required=True),
            DATETIME_REQ, NOTES,
        ],
        "default_lead_times": [10080, 1440, 180],     # 7g + 24h + 3h
        "default_recurrence": None,
        "order_in_category": 20,
    },
    {
        "slug": "restaurant_booking", "category": "events", "icon": "🍽️",
        "title_it": "Prenotazione ristorante",
        "fields": [
            _f("place", "Locale", "text", required=True),
            DATETIME_REQ,
            _f("guests", "Quanti", "text", placeholder="Es. 4 persone"),
        ],
        "default_lead_times": [180, 60],
        "default_recurrence": None,
        "order_in_category": 30,
    },
    {
        "slug": "generic_event", "category": "events", "icon": "📅",
        "title_it": "Altro evento",
        "fields": [
            _f("title", "Titolo", "text", required=True),
            DATETIME_REQ, WHERE, NOTES,
        ],
        "default_lead_times": [1440],
        "default_recurrence": None,
        "order_in_category": 99,
    },
]


# ─── Upsert ───────────────────────────────────────────────────────


async def seed(session: AsyncSession) -> tuple[int, int]:
    """Insert missing templates, update existing ones in place.

    Returns (inserted, updated).
    """
    inserted = 0
    updated = 0

    existing = {
        row.slug: row
        for row in (await session.execute(select(ReminderTemplate))).scalars()
    }

    for t in TEMPLATES:
        slug = t["slug"]
        row = existing.get(slug)
        if row is None:
            session.add(ReminderTemplate(
                slug=slug,
                category=t["category"],
                title_it=t["title_it"],
                icon=t["icon"],
                fields=t["fields"],
                default_lead_times=t["default_lead_times"],
                default_recurrence=t.get("default_recurrence"),
                order_in_category=t.get("order_in_category", 100),
            ))
            inserted += 1
        else:
            changed = False
            for key in ("category", "title_it", "icon", "fields",
                        "default_lead_times", "default_recurrence",
                        "order_in_category"):
                new_val = t.get(key)
                if getattr(row, key) != new_val:
                    setattr(row, key, new_val)
                    changed = True
            if changed:
                updated += 1

    await session.commit()
    return inserted, updated


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        inserted, updated = await seed(session)
    await engine.dispose()
    print(f"reminder_templates: inserted={inserted} updated={updated} "
          f"total_catalog={len(TEMPLATES)}")


if __name__ == "__main__":
    asyncio.run(main())
