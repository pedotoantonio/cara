"""Italian natural-language date/time parser for voice add_task.

Examples handled:
  "domani alle 9"             → tomorrow at 09:00
  "domani alle 9 e mezza"     → tomorrow at 09:30
  "oggi alle 18"              → today at 18:00
  "alle 18"                   → today at 18:00 (or tomorrow if past)
  "lunedì alle 10"            → next Monday at 10:00
  "il 12 maggio alle 9:30"    → May 12 (current year) at 09:30
  "tra 2 ore"                 → now + 2h
  "tra 30 minuti"             → now + 30m
  "stasera"                   → today at 20:00
  "stamattina"                → today at 09:00 (or now+30m if past 09)

Returns a tz-aware datetime in Europe/Rome OR None.
The caller (voice add_task) ALSO gets the residual title with the
date phrase stripped — so "ricordami domani alle 9 di chiamare la zia"
yields title="chiamare la zia", due_date=tomorrow 09:00.

Pure functions, no I/O. ~150 lines, regex-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo


_TZ: Final = ZoneInfo("Europe/Rome")


_WEEKDAYS_IT: Final = {
    "lunedì": 0, "lunedi": 0,
    "martedì": 1, "martedi": 1,
    "mercoledì": 2, "mercoledi": 2,
    "giovedì": 3, "giovedi": 3,
    "venerdì": 4, "venerdi": 4,
    "sabato": 5, "domenica": 6,
}

_MONTHS_IT: Final = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


@dataclass
class ParsedDate:
    when: datetime           # tz-aware in Europe/Rome
    consumed: str            # the substring of the original that matched
                              # — caller strips this to get residual title


# ---------------------------------------------------------------------------
# Time-of-day extractors
# ---------------------------------------------------------------------------

# "alle 9", "alle 9:30", "alle 9 e mezza", "alle 9 e un quarto"
_RE_TIME = re.compile(
    r"\balle?\s+(?P<h>\d{1,2})"
    r"(?:[:.](?P<m>\d{2}))?"
    r"(?:\s+e\s+(?P<frac>mezza|mezzo|un\s+quarto|tre\s+quarti))?"
    r"\b",
    re.IGNORECASE,
)


def _extract_time(text: str) -> tuple[time | None, tuple[int, int] | None]:
    """Return (time, (start, end) span in original) or (None, None)."""
    m = _RE_TIME.search(text)
    if not m:
        return None, None
    h = int(m.group("h"))
    if h > 23:
        return None, None
    minute = 0
    if m.group("m"):
        minute = int(m.group("m"))
        if minute > 59:
            return None, None
    elif m.group("frac"):
        frac = m.group("frac").lower()
        if "mezz" in frac:
            minute = 30
        elif "un quarto" in frac:
            minute = 15
        elif "tre quarti" in frac:
            minute = 45
    return time(h, minute), (m.start(), m.end())


# ---------------------------------------------------------------------------
# Day-of-when extractors
# ---------------------------------------------------------------------------

_RE_RELATIVE_DAY = re.compile(
    r"\b(?P<key>oggi|stasera|stamattina|stanotte|nel\s+pomeriggio|domani|"
    r"dopodomani|dopo\s+domani)\b",
    re.IGNORECASE,
)

_RE_WEEKDAY = re.compile(
    r"\b(?:il\s+|prossim[oa]\s+|gioved\W?[ìi]|"
    r"luned[ìi]|marted[ìi]|mercoled[ìi]|venerd[ìi]|sabato|domenica)\b",
    re.IGNORECASE,
)

_RE_DATE_DMY = re.compile(
    r"\b(?:il\s+)?(?P<d>\d{1,2})\s+(?P<m>"
    + "|".join(_MONTHS_IT.keys())
    + r")(?:\s+(?P<y>\d{4}))?\b",
    re.IGNORECASE,
)

_RE_RELATIVE_OFFSET = re.compile(
    r"\btra\s+(?P<n>\d+|un[ao]?|mezz[ao])\s+"
    r"(?P<unit>minut[oi]|or[ae]|giorn[oi])\b",
    re.IGNORECASE,
)


def _now() -> datetime:
    return datetime.now(_TZ)


def _resolve_relative_day(key: str) -> datetime:
    now = _now()
    key = key.lower().strip()
    if key in ("oggi",):
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if key == "stasera":
        return now.replace(hour=20, minute=0, second=0, microsecond=0)
    if key == "stamattina":
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        # If we're already past 9, schedule 30 min from now (still "stamattina"-ish).
        if now > target:
            target = now + timedelta(minutes=30)
        return target
    if key == "stanotte":
        return now.replace(hour=23, minute=0, second=0, microsecond=0)
    if "pomeriggio" in key:
        return now.replace(hour=15, minute=0, second=0, microsecond=0)
    if key == "domani":
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if "dopo" in key and "domani" in key:
        return (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    return now


def _resolve_weekday(label: str) -> datetime:
    """Return the next occurrence of the given Italian weekday at 00:00."""
    label = label.lower().strip().replace("il ", "").replace("prossimo ", "").replace("prossima ", "")
    target_dow = _WEEKDAYS_IT.get(label)
    if target_dow is None:
        return _now()
    now = _now()
    days_ahead = (target_dow - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # "lunedì" said on a Monday → next Monday
    return (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)


def _resolve_offset(n_str: str, unit: str) -> datetime:
    n_map = {"un": 1, "uno": 1, "una": 1, "mezzo": 0, "mezza": 0}
    if n_str.isdigit():
        n = int(n_str)
    else:
        n = n_map.get(n_str.lower(), 1)
    unit_low = unit.lower()
    now = _now()
    if "minut" in unit_low:
        if "mezz" in n_str.lower():
            return now + timedelta(minutes=30)
        return now + timedelta(minutes=n)
    if "or" in unit_low:
        if "mezz" in n_str.lower():
            return now + timedelta(minutes=30)
        return now + timedelta(hours=n)
    if "giorn" in unit_low:
        return now + timedelta(days=n)
    return now


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def parse_due(text: str) -> ParsedDate | None:
    """Try to find a due-date phrase in `text`. Return a ParsedDate or None.

    Strategy: scan for relative-offset first ("tra 2 ore"), then absolute
    date ("12 maggio"), then weekday, then relative day ("domani"),
    combining with a time-of-day if also present.
    """
    if not text or not text.strip():
        return None

    # 1) "tra N <unit>" — single fragment, no time-of-day combination needed.
    m = _RE_RELATIVE_OFFSET.search(text)
    if m:
        when = _resolve_offset(m.group("n"), m.group("unit"))
        return ParsedDate(when=when, consumed=m.group(0))

    # 2) Time-of-day always extracted first when present.
    tod, tod_span = _extract_time(text)

    # 3) Absolute date "12 maggio [2026]" wins over weekday/relative.
    m_date = _RE_DATE_DMY.search(text)
    if m_date:
        d = int(m_date.group("d"))
        mon = _MONTHS_IT[m_date.group("m").lower()]
        y_str = m_date.group("y")
        now = _now()
        y = int(y_str) if y_str else now.year
        try:
            base = datetime(y, mon, d, tzinfo=_TZ)
        except ValueError:
            return None
        if tod is not None:
            base = base.replace(hour=tod.hour, minute=tod.minute)
        # If the date already passed this year and no year given, bump.
        if y_str is None and base < now:
            base = base.replace(year=y + 1)
        consumed = m_date.group(0)
        if tod_span is not None:
            consumed = consumed + " " + text[tod_span[0]:tod_span[1]]
        return ParsedDate(when=base, consumed=consumed)

    # 4) Weekday name.
    m_wd = _RE_WEEKDAY.search(text)
    if m_wd:
        base = _resolve_weekday(m_wd.group(0))
        if tod is not None:
            base = base.replace(hour=tod.hour, minute=tod.minute)
        consumed = m_wd.group(0)
        if tod_span is not None:
            consumed += " " + text[tod_span[0]:tod_span[1]]
        return ParsedDate(when=base, consumed=consumed)

    # 5) Relative day (oggi/domani/...).
    m_rd = _RE_RELATIVE_DAY.search(text)
    if m_rd:
        base = _resolve_relative_day(m_rd.group("key"))
        if tod is not None:
            base = base.replace(hour=tod.hour, minute=tod.minute)
        consumed = m_rd.group(0)
        if tod_span is not None:
            consumed += " " + text[tod_span[0]:tod_span[1]]
        return ParsedDate(when=base, consumed=consumed)

    # 6) Bare time-of-day → today (or tomorrow if past).
    if tod is not None and tod_span is not None:
        now = _now()
        candidate = now.replace(
            hour=tod.hour, minute=tod.minute, second=0, microsecond=0,
        )
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return ParsedDate(when=candidate, consumed=text[tod_span[0]:tod_span[1]])

    return None


def strip_date_phrase(text: str, parsed: ParsedDate) -> str:
    """Remove the consumed date-phrase from the original text and clean up."""
    if not text or not parsed.consumed:
        return text
    # Be lenient: case-insensitive, single occurrence.
    pat = re.compile(re.escape(parsed.consumed), re.IGNORECASE)
    out = pat.sub("", text, count=1)
    # Common connectors left dangling: "di", " di " before/after the phrase.
    out = re.sub(r"\b(?:di|,)\s+(?:di\s+)?", " ", out)
    out = re.sub(r"\s+", " ", out).strip(" ,.;:")
    return out
