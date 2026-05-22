"""LifeOps Intent Router — Tier-0 regex matcher (M1).

Pattern italiani per matching deterministico SENZA LLM. Coperture M1:
- reminder con datetime relativo ("tra 20 minuti", "fra mezz'ora")
- reminder con datetime assoluto ("domani alle 16:30", "lunedì alle 9")
- reminder ricorrente ("ogni lunedì alle 9")
- list_add ("aggiungi X alla spesa", "aggiungi 2 chili di Y")
- list_query ("cosa c'è nella spesa", "cosa devo fare")
- list_done ("ho preso il pane", "comprato")

Filosofia: meglio `UnsureIntent` di risposta inventata. La M1.5
sostituisce questa funzione con NLU LLM full quando arriva cara-llm
separato (Ondata δ).

Funzione principale:
    route(utterance: str, *, now_utc: datetime, list_slugs: list[str])
        -> Intent
"""

from __future__ import annotations

import re
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

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


# Mapping parola → category_slug per il classificatore finance.
_FINANCE_KEYWORDS = {
    "farmacia": "salute",
    "medico": "salute",
    "dottore": "salute",
    "ospedale": "salute",
    "medicina": "salute",
    "medicine": "salute",
    "supermercato": "spesa",
    "spesa": "spesa",
    "spese alimentari": "spesa",
    "frutta": "spesa",
    "verdura": "spesa",
    "pane": "spesa",
    "carne": "spesa",
    "benzina": "trasporti",
    "carburante": "trasporti",
    "treno": "trasporti",
    "biglietto": "trasporti",
    "auto": "trasporti",
    "moto": "trasporti",
    "metro": "trasporti",
    "ristorante": "ristoranti",
    "pizzeria": "ristoranti",
    "bar": "ristoranti",
    "pranzo": "ristoranti",
    "cena": "ristoranti",
    "caffè": "ristoranti",
    "caffe": "ristoranti",
    "cinema": "tempo_libero",
    "concerto": "tempo_libero",
    "libro": "tempo_libero",
    "libri": "tempo_libero",
    "videogioco": "tempo_libero",
    "netflix": "abbonamenti",
    "spotify": "abbonamenti",
    "abbonamento": "abbonamenti",
    "regalo": "regali",
    "regali": "regali",
    "compleanno": "regali",
    "scuola": "bimbi",
    "doposcuola": "bimbi",
    "asilo": "bimbi",
    "lezioni": "bimbi",
    "bollett": "casa",  # bolletta/e
    "luce": "casa",
    "gas": "casa",
    "acqua": "casa",
    "internet": "casa",
    "affitto": "casa",
    "mutuo": "casa",
    "stipendio": "stipendio",
    "salario": "stipendio",
    "paga": "stipendio",
    "bonus": "stipendio",
}


ROME = ZoneInfo("Europe/Rome")


# ── Day-of-week IT ──────────────────────────────────────────────────

_DOW = {
    "lunedì": 0, "lunedi": 0,
    "martedì": 1, "martedi": 1,
    "mercoledì": 2, "mercoledi": 2,
    "giovedì": 3, "giovedi": 3,
    "venerdì": 4, "venerdi": 4,
    "sabato": 5,
    "domenica": 6,
}

# Month IT for "il 12 marzo" patterns
_MONTH = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

# Quantità numeriche scritte
_WRITTEN_QTY: dict[str, float] = {
    "uno": 1, "una": 1, "un": 1,
    "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
    "venti": 20, "trenta": 30, "quaranta": 40,
    "cinquanta": 50, "sessanta": 60,
    "mezzo": 0.5, "mezza": 0.5,
}

# Unità di misura
_UNIT_ALIASES = {
    "kg": "kg", "chilo": "kg", "chili": "kg", "chilogrammo": "kg",
    "g": "g", "grammo": "g", "grammi": "g",
    "litro": "l", "litri": "l", "l": "l",
    "ml": "ml",
    "pezzi": "pz", "pezzo": "pz", "pz": "pz",
    "confezioni": "conf", "confezione": "conf",
    "bottiglie": "btl", "bottiglia": "btl",
}


# ── Parsers ─────────────────────────────────────────────────────────


def _parse_time(s: str) -> dtime | None:
    """Parse '16:30' / '16.30' / '9' / '21' → time."""
    s = s.strip().replace(".", ":")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?$", s)
    if not m:
        return None
    h = int(m.group(1))
    mm = int(m.group(2) or 0)
    if 0 <= h < 24 and 0 <= mm < 60:
        return dtime(h, mm)
    return None


def _next_dow(now_local: datetime, target_dow: int) -> datetime:
    """Prossimo `target_dow` rispetto a now_local. Se è oggi e ora
    successiva, considera oggi; altrimenti settimana prossima."""
    delta = (target_dow - now_local.weekday()) % 7
    if delta == 0:
        # potrebbe essere oggi stesso (se ora è ancora avanti) — caller decide
        return now_local
    return now_local + timedelta(days=delta)


_REL_NUM_TOKEN = (
    r"\d+|un|uno|una|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|"
    r"venti|trenta|quaranta|cinquanta|sessanta"
)


def _parse_relative_minutes(s: str) -> int | None:
    """Parse 'tra 20 minuti', 'fra mezz'ora', 'tra un'ora'. Cerca
    anywhere nella stringa (search, non match)."""
    s = s.lower()
    # "fra mezz'ora" / "tra mezz'ora" (apostrofo standard o curly)
    if re.search(r"\b(tra|fra)\s+mezz[''o]\s*ora\b", s):
        return 30
    # "tra un'ora" / "fra un'ora"
    if re.search(r"\b(tra|fra)\s+un['']?\s*ora\b", s):
        return 60
    # "tra X minuti" / "tra X ore"
    m = re.search(
        r"\b(?:tra|fra)\s+(" + _REL_NUM_TOKEN + r")\s+(minuti?|ore?)\b",
        s,
    )
    if m:
        n = m.group(1)
        unit = m.group(2)
        amount = int(n) if n.isdigit() else _WRITTEN_QTY.get(n, 1)
        if unit.startswith("min"):
            return int(amount)
        return int(amount * 60)
    return None


_REL_PHRASE_RX = re.compile(
    r"\b((?:tra|fra)\s+(?:mezz[''o]\s*ora|un['']?\s*ora|(?:"
    + _REL_NUM_TOKEN
    + r")\s+(?:minuti?|ore?)))\b",
    re.IGNORECASE,
)


def _strip_rel_phrase(s: str) -> str:
    """Rimuove la frase 'tra X minuti/ore' dal titolo."""
    return _REL_PHRASE_RX.sub("", s, count=1)


def _parse_qty(s: str) -> tuple[float, str | None, str]:
    """Estrai quantità da inizio frase: '2 chili di pomodori' →
    (2, 'kg', 'pomodori'). Ritorna (qty, unit, remainder)."""
    m = re.match(
        r"^\s*(\d+(?:[.,]\d+)?|uno|una|un|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|venti|trenta|mezzo|mezza)"
        r"(?:\s+(kg|chil[oi]|chilogramm[io]|g|gramm[io]|litr[oi]|l|ml|pezz[io]|pz|confezion[ei]|bottigli[ea]|pacch[io]|pacc[ho]))?"
        r"\s+(?:di\s+)?(.+)$",
        s.strip(),
        re.IGNORECASE,
    )
    if not m:
        return (1.0, None, s.strip())
    qty_s = m.group(1).lower()
    unit_s = (m.group(2) or "").lower()
    rest = m.group(3).strip()
    qty = (
        float(qty_s.replace(",", "."))
        if re.match(r"^\d", qty_s)
        else _WRITTEN_QTY.get(qty_s, 1)
    )
    unit = _UNIT_ALIASES.get(unit_s) if unit_s else None
    return (qty, unit, rest)


# ── Helpers slug matching ───────────────────────────────────────────


def _guess_list_slug(text: str, available: list[str]) -> str | None:
    """Map text mentioning 'spesa', 'cose da fare', ecc. → slug.
    Cerca prima un match esatto nello slug, poi un alias."""
    aliases = {
        "spesa": "shopping",
        "supermercato": "shopping",
        "lista": None,
        "cose da fare": "todo",
        "cose da far": "todo",
        "task": "todo",
        "todo": "todo",
        "da fare": "todo",
    }
    low = text.lower()
    for alias, slug in aliases.items():
        if alias in low:
            if slug and slug in available:
                return slug
            if alias in available:
                return alias
    # Fallback: cerca slug stesso nella frase
    for slug in available:
        if slug in low:
            return slug
    return None


# ── Main entrypoint ──────────────────────────────────────────────────


def route(
    utterance: str,
    *,
    now_utc: datetime | None = None,
    list_slugs: list[str] | None = None,
) -> Intent:
    """Tier-0 router. Ritorna Intent tipizzato. UnsureIntent quando
    nessun pattern matcha."""
    text = utterance.strip()
    low = text.lower()
    list_slugs = list_slugs or ["shopping", "todo"]
    now_utc = now_utc or datetime.now(timezone.utc)
    now_local = now_utc.astimezone(ROME)

    # ── FINANCE — query (sum/etc) ───────────────────────────────

    fin_q = _try_finance_query(low)
    if fin_q is not None:
        return fin_q

    # ── FINANCE — transaction_add ───────────────────────────────

    tx_add = _try_transaction_add(text, low)
    if tx_add is not None:
        return tx_add

    # ── REMINDERS ────────────────────────────────────────────────

    # "ogni <dow> alle <hh>" ricorrente settimanale
    m = re.search(
        r"\bogni\s+(lunedì|lunedi|martedì|martedi|mercoledì|mercoledi|giovedì|giovedi|venerdì|venerdi|sabato|domenica)"
        r"(?:\s+alle?\s+(\d{1,2}(?::\d{2})?))?\b",
        low,
    )
    if m:
        dow = _DOW[m.group(1)]
        hh = m.group(2)
        t = _parse_time(hh) if hh else dtime(9, 0)
        title = re.sub(
            r"\b(ricordami(?: di)?|promemoria|ogni)\b.*?(?=$|\.)",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        ).strip(" .,:;")
        title = title or "Promemoria settimanale"
        dow_byday = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][dow]
        rrule = f"FREQ=WEEKLY;BYDAY={dow_byday};BYHOUR={t.hour};BYMINUTE={t.minute}"
        return ReminderIntent(title=title, fires_at=None, rrule=rrule)

    # "ricordami / promemoria / tra X / fra X"
    if re.search(r"\b(ricordami|ricorda(?:mi)?|promemoria)\b", low) or low.startswith(("tra ", "fra ")):
        # Estrai titolo (toglie i prefissi tipo "ricordami di X")
        title = re.sub(
            r"^(ricordami(?:\s+di)?|ricorda(?:mi)?|promemoria(?:\s+di)?)\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        # Datetime relativo "tra X minuti/ore"
        rel = _parse_relative_minutes(low)
        if rel is not None:
            fires_at = now_utc + timedelta(minutes=rel)
            # Strip the rel-phrase + "ricordami di" + "chiamare"-style verbs
            # so the title is just the action object.
            title = _strip_rel_phrase(title)
            title = re.sub(r"^di\s+", "", title.strip(), flags=re.IGNORECASE)
            return ReminderIntent(
                title=_clean_title(title), fires_at=fires_at
            )

        # "domani alle HH"
        m = re.search(r"\bdomani\s+alle?\s+(\d{1,2}(?::\d{2})?)\b", low)
        if m:
            t = _parse_time(m.group(1))
            if t:
                tomorrow = (now_local + timedelta(days=1)).date()
                local_dt = datetime.combine(tomorrow, t, tzinfo=ROME)
                fires_at = local_dt.astimezone(timezone.utc)
                title = re.sub(r"\bdomani\s+alle?\s+\d{1,2}(?::\d{2})?\b", "", title, flags=re.IGNORECASE).strip(" :,.")
                return ReminderIntent(title=_clean_title(title), fires_at=fires_at)

        # "lunedì alle HH" (prossima occorrenza)
        m = re.search(
            r"\b(lunedì|lunedi|martedì|martedi|mercoledì|mercoledi|giovedì|giovedi|venerdì|venerdi|sabato|domenica)"
            r"\s+alle?\s+(\d{1,2}(?::\d{2})?)\b",
            low,
        )
        if m:
            dow = _DOW[m.group(1)]
            t = _parse_time(m.group(2))
            if t:
                target = _next_dow(now_local, dow)
                local_dt = datetime.combine(target.date(), t, tzinfo=ROME)
                # Se target è oggi ma l'ora è passata, sposta a +7
                if local_dt <= now_local:
                    local_dt = local_dt + timedelta(days=7)
                fires_at = local_dt.astimezone(timezone.utc)
                title = re.sub(
                    r"\b(lunedì|lunedi|martedì|martedi|mercoledì|mercoledi|giovedì|giovedi|venerdì|venerdi|sabato|domenica)\s+alle?\s+\d{1,2}(?::\d{2})?\b",
                    "",
                    title,
                    flags=re.IGNORECASE,
                ).strip(" :,.")
                return ReminderIntent(title=_clean_title(title), fires_at=fires_at)

        # "il 12 marzo" → ricorrenza yearly
        m = re.search(
            r"\bil\s+(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\b",
            low,
        )
        if m:
            day = int(m.group(1))
            month = _MONTH[m.group(2)]
            year = now_local.year
            target = datetime(year, month, day, 9, 0, tzinfo=ROME)
            if target <= now_local:
                target = target.replace(year=year + 1)
            fires_at = target.astimezone(timezone.utc)
            # Anniversari → yearly
            rrule = f"FREQ=YEARLY;BYMONTH={month};BYMONTHDAY={day}"
            title = re.sub(
                r"\bil\s+\d{1,2}\s+\w+\b",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip(" :,.")
            return ReminderIntent(
                title=_clean_title(title), fires_at=fires_at, rrule=rrule
            )

        # Niente datetime trovato → unsure
        return UnsureIntent(
            reason="reminder senza datetime parsabile",
            suggested_clarification="Quando devo ricordartelo?",
        )

    # ── LIST_DONE ────────────────────────────────────────────────

    m = re.match(
        r"^(?:ho\s+(?:preso|comprato|fatto)|comprato|preso)\s+(?:il\s+|la\s+|i\s+|le\s+|lo\s+|gli\s+)?(.+?)\s*$",
        low,
    )
    if m:
        item = m.group(1).strip(" .,!?")
        # Default lista → shopping
        slug = "shopping" if "shopping" in list_slugs else (list_slugs[0] if list_slugs else "shopping")
        return ListDoneIntent(list_slug=slug, item_substring=item)

    # ── LIST_ADD ─────────────────────────────────────────────────

    # "aggiungi X alla/lista Y" / "aggiungi X" (default shopping)
    m = re.match(
        r"^aggiungi\s+(?:alla\s+lista\s+(?:della\s+)?\w+\s*:\s*)?(.+?)(?:\s+(?:alla|nella)\s+(?:lista\s+(?:della\s+)?)?(.+))?$",
        low,
    )
    if m:
        item_text = m.group(1).strip()
        list_hint = (m.group(2) or "").strip()
        slug = _guess_list_slug(list_hint or text, list_slugs) or (
            "shopping" if "shopping" in list_slugs else (list_slugs[0] if list_slugs else "shopping")
        )
        qty, unit, name = _parse_qty(item_text)
        return ListAddIntent(
            list_slug=slug,
            item=name.capitalize(),
            qty=qty if qty != 1.0 or unit is not None else None,
            unit=unit,
        )

    # "ho bisogno di X" / "mi serve X" → list_add su shopping
    m = re.match(r"^(?:ho\s+bisogno\s+di|mi\s+serve|mi\s+servono)\s+(.+?)\s*$", low)
    if m:
        item_text = m.group(1).strip()
        qty, unit, name = _parse_qty(item_text)
        return ListAddIntent(
            list_slug="shopping" if "shopping" in list_slugs else (list_slugs[0] if list_slugs else "shopping"),
            item=name.capitalize(),
            qty=qty if qty != 1.0 or unit is not None else None,
            unit=unit,
        )

    # ── LIST_QUERY ───────────────────────────────────────────────

    # "cosa devo comprare?", "cosa c'è nella spesa?", "cosa devo fare?"
    if re.search(
        r"\b(cosa|che)\s+(devo|c['eè]+)\s+(fare|comprare|prendere|nella|in|nelle|in lista)\b",
        low,
    ):
        slug = _guess_list_slug(low, list_slugs)
        if slug is None:
            if "comprare" in low or "prendere" in low or "spesa" in low:
                slug = "shopping" if "shopping" in list_slugs else None
            elif "fare" in low:
                slug = "todo" if "todo" in list_slugs else None
        return ListQueryIntent(list_slug=slug)

    # Default → unsure
    return UnsureIntent(
        reason="Nessun pattern lifeops M1 ha matchato",
        suggested_clarification=None,
    )


def _classify_finance_category(text: str) -> str | None:
    """Cerca keyword italiane → slug categoria."""
    low = text.lower()
    for kw, slug in _FINANCE_KEYWORDS.items():
        if kw in low:
            return slug
    return None


def _parse_amount_it(s: str) -> Decimal | None:
    """Parse '12 euro', '12.50', '1.200 euro', '1,50', 'trecento euro'.
    Returns Decimal or None.
    """
    s = s.strip().lower()
    # Forme numeriche '12.50', '12,50', '1.200,50', '1200'
    # Italian: , è decimale, . è migliaia
    m = re.search(
        r"\b(\d{1,3}(?:[.,]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
        r"\s*(?:eur(?:o|i)?|€|euro)?\b",
        s,
    )
    if m:
        num = m.group(1)
        # Detect formato: se ha ',' e poi 1-2 cifre, è decimale.
        # Altrimenti '.', se 3 cifre dopo = migliaia, else decimale.
        if "," in num:
            # rimuovi '.' di migliaia, sostituisci ',' con '.'
            num_norm = num.replace(".", "").replace(",", ".")
        elif num.count(".") == 1:
            parts = num.split(".")
            if len(parts[1]) == 3:
                # migliaia
                num_norm = num.replace(".", "")
            else:
                num_norm = num
        else:
            num_norm = num.replace(".", "")
        try:
            return Decimal(num_norm).quantize(Decimal("0.01"))
        except Exception:
            return None
    # Numeri scritti (limitato)
    written = {
        "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
        "dieci": 10, "venti": 20, "trenta": 30, "quaranta": 40,
        "cinquanta": 50, "cento": 100, "duecento": 200, "trecento": 300,
        "quattrocento": 400, "cinquecento": 500, "mille": 1000,
    }
    for k, v in written.items():
        if re.search(rf"\b{k}\s*euro?", s):
            return Decimal(v).quantize(Decimal("0.01"))
    return None


def _try_transaction_add(text: str, low: str) -> TransactionAddIntent | None:
    """Pattern: 'ho speso X', 'ho pagato X', 'segna X per Y',
    'mi sono entrati X', 'ho preso X di stipendio'.
    """
    # Direction inference + extract amount + description
    if re.search(
        r"\b(ho\s+speso|ho\s+pagato|spesi?|pagato|segna\s+\d|paga(?:to|i))\b",
        low,
    ):
        amount = _parse_amount_it(low)
        if not amount:
            return None
        # description: prendi tutto tranne il numero
        desc = re.sub(
            r"\b(?:ho\s+speso|ho\s+pagato|spes[ai]?|pagato|segna|paga(?:to|i))\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
        desc = re.sub(
            r"\b\d{1,3}(?:[.,]\d{3})*(?:,\d{1,2})?(?:\s*(?:eur(?:o|i)?|€))?\b",
            "",
            desc,
            flags=re.IGNORECASE,
        )
        desc = re.sub(r"\b(?:per|in|al|alla|allo|ai|alle)\b", " ", desc).strip(" .,!?")
        desc = re.sub(r"\s+", " ", desc) or None
        category = _classify_finance_category(text)
        return TransactionAddIntent(
            amount=amount,
            direction="expense",
            description=desc.capitalize() if desc else None,
            category_slug=category,
        )

    # Income
    if re.search(
        r"\b(mi\s+sono\s+entrati|ho\s+preso\s+\d|mi\s+hanno\s+pagato|ricevuto)\b",
        low,
    ):
        amount = _parse_amount_it(low)
        if not amount:
            return None
        category = _classify_finance_category(text) or "entrate_varie"
        desc = "Stipendio" if "stipendio" in low else None
        return TransactionAddIntent(
            amount=amount,
            direction="income",
            description=desc,
            category_slug=category,
        )
    return None


def _try_finance_query(low: str) -> FinanceQueryIntent | None:
    """Pattern: 'quanto ho speso', 'quanto ho guadagnato', 'quanto in farmacia'."""
    if not re.search(r"\bquanto\s+(?:ho|sono|c['e])?\b", low):
        return None
    direction: str | None = None
    if "speso" in low or "spese" in low or "pagato" in low:
        direction = "expense"
    elif "guadagn" in low or "incass" in low or "entrate" in low:
        direction = "income"

    category = _classify_finance_category(low)

    # Period hint
    period_hint = None
    if "oggi" in low:
        period_hint = "oggi"
    elif "ieri" in low:
        period_hint = "ieri"
    elif "settimana" in low:
        period_hint = "settimana"
    elif re.search(r"\bquest['o]?\s+mese\b|\bnel\s+mese\b|\bal\s+mese\b|\bmese\s+corrente\b", low):
        period_hint = "mese"
    elif "anno" in low:
        period_hint = "anno"
    elif "maggio" in low or "giugno" in low or "luglio" in low or "agosto" in low:
        # mese specifico → period_hint stesso nome
        for m_name in _MONTH:
            if m_name in low:
                period_hint = m_name
                break

    return FinanceQueryIntent(
        metric="sum",
        direction=direction,  # type: ignore[arg-type]
        category_slug=category,
        period_hint=period_hint,
    )


def _clean_title(title: str) -> str:
    """Pulizia minima del titolo del reminder."""
    title = re.sub(r"\s+", " ", title).strip(" .,:;")
    # Capitalize first letter, leave rest
    if title and title[0].islower():
        title = title[0].upper() + title[1:]
    return title or "Promemoria"
