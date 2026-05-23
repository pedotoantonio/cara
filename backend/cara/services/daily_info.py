"""Daily info service — informazioni utili per ogni giorno del calendario.

Combina festività italiane + santi + fase lunare + alba/tramonto Ferrara +
stagione + proverbi italiani + countdown eventi rilevanti in un singolo
oggetto per data.

Pure functions: niente DB, niente network. Tutto calcolabile dalla data.
Per la geolocalizzazione del sole usiamo Ferrara fissa (44.838, 11.621).
Per altre città si può estendere passando lat/lon.

Endpoint: /api/v1/calendar/day-info?date=YYYY-MM-DD
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from cara.services.saints import saint_for


ROME = ZoneInfo("Europe/Rome")

# Default city: Ferrara (residenza famiglia Pedoto)
DEFAULT_LAT = 44.83804
DEFAULT_LON = 11.62057


# ─── Festività italiane ─────────────────────────────────────────────


def _easter_sunday(y: int) -> date:
    """Anonymous Gregorian algorithm — Computus."""
    a = y % 19
    b = y // 100
    c = y % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    month = (h + L - 7 * m + 114) // 31
    day = ((h + L - 7 * m + 114) % 31) + 1
    return date(y, month, day)


_FIXED_HOLIDAYS: dict[tuple[int, int], str] = {
    (1, 1): "Capodanno",
    (1, 6): "Epifania",
    (4, 25): "Festa della Liberazione",
    (5, 1): "Festa del lavoro",
    (6, 2): "Festa della Repubblica",
    (8, 15): "Ferragosto",
    (11, 1): "Tutti i santi",
    (12, 8): "Immacolata Concezione",
    (12, 25): "Natale",
    (12, 26): "Santo Stefano",
}


def _holiday_for(d: date) -> str | None:
    fixed = _FIXED_HOLIDAYS.get((d.month, d.day))
    if fixed:
        return fixed
    e = _easter_sunday(d.year)
    if d == e:
        return "Pasqua"
    if d == e + timedelta(days=1):
        return "Pasquetta"
    # Other movable (non-festivi nazionali ma rilevanti)
    if d == e - timedelta(days=2):
        return "Venerdì Santo"
    if d == e - timedelta(days=7):
        return "Domenica delle Palme"
    if d == e + timedelta(days=49):
        return "Pentecoste"
    if d == date(d.year, 12, 24):
        return "Vigilia di Natale"
    if d == date(d.year, 12, 31):
        return "San Silvestro"
    return None


# ─── Stagione ────────────────────────────────────────────────────────


def _season_for(d: date) -> str:
    """Stagione astronomica IT (~equinozi/solstizi)."""
    y = d.year
    spring = date(y, 3, 20)
    summer = date(y, 6, 21)
    autumn = date(y, 9, 22)
    winter = date(y, 12, 21)
    if d < spring or d >= winter:
        return "inverno"
    if d < summer:
        return "primavera"
    if d < autumn:
        return "estate"
    return "autunno"


# ─── Fase lunare ─────────────────────────────────────────────────────


def _moon_phase(d: date) -> tuple[str, float]:
    """Fase lunare semplificata. Ritorna (label, illumination 0..1).

    Algoritmo: ciclo sinodico 29.53059 giorni a partire da una
    new moon di riferimento (2000-01-06 18:14 UT).
    """
    # Riferimento: 2000-01-06 18:14 UT new moon, Julian = 2451550.1
    ref = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    dt = datetime.combine(d, time(12, 0, tzinfo=timezone.utc))
    delta_days = (dt - ref).total_seconds() / 86400.0
    cycle = 29.53058867
    phase = (delta_days % cycle) / cycle  # 0..1
    # Illumination ≈ (1 - cos(2π·phase)) / 2
    illum = (1 - math.cos(2 * math.pi * phase)) / 2

    if phase < 0.03 or phase > 0.97:
        label = "luna nuova"
    elif phase < 0.22:
        label = "luna crescente"
    elif phase < 0.28:
        label = "primo quarto"
    elif phase < 0.47:
        label = "gibbosa crescente"
    elif phase < 0.53:
        label = "luna piena"
    elif phase < 0.72:
        label = "gibbosa calante"
    elif phase < 0.78:
        label = "ultimo quarto"
    else:
        label = "luna calante"
    return label, round(illum, 3)


_MOON_EMOJI = {
    "luna nuova": "🌑",
    "luna crescente": "🌒",
    "primo quarto": "🌓",
    "gibbosa crescente": "🌔",
    "luna piena": "🌕",
    "gibbosa calante": "🌖",
    "ultimo quarto": "🌗",
    "luna calante": "🌘",
}


# ─── Alba e tramonto ────────────────────────────────────────────────


def _sunrise_sunset(
    d: date, lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON
) -> tuple[time | None, time | None]:
    """Alba e tramonto per lat/lon a una data. Ritorna (alba, tramonto)
    in Europe/Rome local time. None se sole circumpolare (mai per Italia).

    Algoritmo NOAA semplificato (Spencer 1971 declination + standard
    refraction zenith 90.833°). Precisione ±1-2 min, sufficiente per
    info giornaliera.
    """
    n = d.toordinal() - date(d.year, 1, 1).toordinal() + 1
    # Solar mean anomaly + ecliptic longitude
    gamma = 2 * math.pi / 365 * (n - 1)
    # Declination del sole (Spencer)
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.001480 * math.sin(3 * gamma)
    )
    # Equation of time (minuti)
    eq_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    lat_r = math.radians(lat)
    # Zenith for sunrise/sunset (refraction-corrected)
    zenith_r = math.radians(90.833)
    cos_h = (
        math.cos(zenith_r) - math.sin(lat_r) * math.sin(decl)
    ) / (math.cos(lat_r) * math.cos(decl))
    if cos_h > 1 or cos_h < -1:
        return None, None  # sole mai sopra/sotto orizzonte
    h = math.degrees(math.acos(cos_h))
    # Solar noon UTC (minuti dalla mezzanotte)
    noon_min = 720 - 4 * lon - eq_time
    sunrise_min = noon_min - 4 * h
    sunset_min = noon_min + 4 * h

    def _to_local_time(mins_utc: float) -> time:
        # Wrap-around
        mins_utc = mins_utc % 1440
        utc_dt = datetime.combine(d, time(0, 0, tzinfo=timezone.utc)) + timedelta(
            minutes=mins_utc
        )
        local = utc_dt.astimezone(ROME)
        return local.time().replace(microsecond=0)

    return _to_local_time(sunrise_min), _to_local_time(sunset_min)


# ─── Proverbi italiani ──────────────────────────────────────────────


_PROVERBS_BY_MONTH: dict[int, list[str]] = {
    1: [
        "Sotto la neve pane, sotto la pioggia fame.",
        "Befana vien di notte con le scarpe tutte rotte.",
        "Gennaio asciutto, gran per tutto.",
        "Anno nuovo, vita nuova.",
    ],
    2: [
        "Per Sant'Agata il freddo è una bagattella.",
        "Per la Candelora, dell'inverno semo fora.",
        "Febbraio, febbraietto, corto e maledetto.",
        "Quando la merla passa il fiume, l'inverno è alle spalle.",
    ],
    3: [
        "Marzo pazzerello, esce il sole e prendi l'ombrello.",
        "Marzo è ostinato, ma poi guarisce il prato.",
        "San Giuseppe il falegname porta polvere e affamà.",
        "Aprile e maggio fanno il chicco e il grano.",
    ],
    4: [
        "Aprile, ogni giorno un barile.",
        "Aprile dolce dormire.",
        "San Marco evangelista cinquantatré giorni alla Madonna acquista.",
        "Aprile non ti scoprire, maggio adagio.",
    ],
    5: [
        "Maggio asciutto, gran per tutto.",
        "Maggio fiorito vale un palio incoronato.",
        "Per San Giovanni la melanzana, per San Lorenzo la castagna.",
        "Sposa di maggio, sposa di disagio.",
    ],
    6: [
        "Giugno la falce in pugno.",
        "Per San Giovanni si raccolgono i meloni.",
        "Sole di giugno fa il grano d'oro.",
        "A San Pietro acqua benedetta.",
    ],
    7: [
        "Luglio caldo, pane in regalo.",
        "Acqua di luglio, semina d'agosto.",
        "Luglio porta via il bucato.",
        "Per San Giacomo l'uva si tinge.",
    ],
    8: [
        "Agosto matura, settembre vendemmia.",
        "Agosto e tempo bello scioglie il giogo al bovarello.",
        "Per Ferragosto, mezza estate dorme nel bosco.",
        "Sole d'agosto, dieci uomini al posto.",
    ],
    9: [
        "Settembre porta uva e fichi a chi non ha amici.",
        "Per San Matteo le rondini al ballo.",
        "Settembre ventoso, freddo doloroso.",
        "Mese vendemmiale, mese felice.",
    ],
    10: [
        "Ottobre piovoso, gennaio nevoso.",
        "Per San Luca, semina senza paura.",
        "Ottobre è festa di colori.",
        "Per San Simone il ventaglio si ripone.",
    ],
    11: [
        "Per i Santi, la neve sui campi.",
        "Novembre, dei contadini il sepolcro.",
        "Per San Martino la castagna e il vino.",
        "L'autunno cede, l'inverno avanza.",
    ],
    12: [
        "Per Santa Lucia, il giorno più corto che ci sia.",
        "Natale al sole, Pasqua al focolare.",
        "Dicembre, gelo e piacere.",
        "L'anno se ne va col canto del gallo.",
    ],
}


def _proverb_for(d: date) -> str:
    """Sceglie un proverbio del mese, rotazione deterministica sul giorno."""
    candidates = _PROVERBS_BY_MONTH.get(d.month, [])
    if not candidates:
        return ""
    return candidates[d.day % len(candidates)]


# ─── Countdown eventi ────────────────────────────────────────────────


def _countdowns(d: date) -> list[dict[str, str | int]]:
    """Conta giorni a eventi rilevanti futuri (entro 12 mesi)."""
    items: list[dict[str, str | int]] = []
    y = d.year

    candidates: list[tuple[date, str, str]] = [
        (_easter_sunday(y), "Pasqua", "🐣"),
        (date(y, 6, 21), "Inizio estate", "☀️"),
        (date(y, 8, 15), "Ferragosto", "🏖️"),
        (date(y, 9, 23), "Inizio autunno", "🍂"),
        (date(y, 10, 31), "Halloween", "🎃"),
        (date(y, 11, 1), "Tutti i Santi", "🕊️"),
        (date(y, 12, 24), "Vigilia di Natale", "🎄"),
        (date(y, 12, 25), "Natale", "🎁"),
        (date(y, 12, 31), "Capodanno", "🎉"),
    ]
    # Rolling year (se un evento è passato, usa l'anno successivo)
    rolling: list[tuple[date, str, str]] = []
    for ev, label, emoji in candidates:
        target = ev if ev >= d else date(y + 1, ev.month, ev.day)
        rolling.append((target, label, emoji))
    # Easter year+1 caso
    e_next = _easter_sunday(y + 1)
    if _easter_sunday(y) < d:
        rolling = [(e_next if lbl == "Pasqua" else t, lbl, em) for t, lbl, em in rolling]

    rolling.sort(key=lambda x: x[0])
    for target, label, emoji in rolling[:4]:  # Top 4 imminenti
        delta = (target - d).days
        items.append({
            "label": label,
            "emoji": emoji,
            "date": target.isoformat(),
            "days_to": delta,
        })
    return items


# ─── Italian day name + week info ───────────────────────────────────


_DAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MONTHS_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


# ─── Output dataclass ───────────────────────────────────────────────


@dataclass(slots=True)
class DayInfo:
    iso: str
    day_name_it: str
    month_name_it: str
    long_format_it: str
    week_number: int
    is_weekend: bool
    is_holiday: bool
    holiday_name: str | None
    season: Literal["inverno", "primavera", "estate", "autunno"]
    saint: str | None
    moon_phase: str
    moon_phase_emoji: str
    moon_illumination: float
    sunrise: str | None  # HH:MM
    sunset: str | None
    daylight_hours: float | None
    proverb: str
    countdowns: list[dict[str, str | int]]
    notes: list[str]


def info_for(
    d: date,
    *,
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
) -> DayInfo:
    """Costruisce il payload completo per una data."""
    holiday = _holiday_for(d)
    season = _season_for(d)
    saint = saint_for(d)
    moon_lbl, moon_illum = _moon_phase(d)
    sunrise, sunset = _sunrise_sunset(d, lat, lon)
    daylight = None
    if sunrise and sunset:
        daylight = (
            (datetime.combine(d, sunset) - datetime.combine(d, sunrise)).total_seconds()
            / 3600.0
        )
    week_num = int(d.strftime("%V"))
    long_fmt = f"{_DAYS_IT[d.weekday()]} {d.day} {_MONTHS_IT[d.month - 1]} {d.year}"

    # Notes: collezione di info contestuali "carine"
    notes: list[str] = []
    if holiday:
        notes.append(f"Oggi è {holiday}.")
    if saint:
        notes.append(f"San/Santa del giorno: {saint}.")
    if moon_lbl == "luna piena":
        notes.append("È luna piena.")
    elif moon_lbl == "luna nuova":
        notes.append("È luna nuova.")
    if season == "primavera" and d.day == 21 and d.month == 3:
        notes.append("Equinozio di primavera. 🌷")
    if season == "estate" and d.day == 21 and d.month == 6:
        notes.append("Solstizio d'estate, il giorno più lungo dell'anno. ☀️")
    if season == "autunno" and d.day == 23 and d.month == 9:
        notes.append("Equinozio d'autunno. 🍂")
    if season == "inverno" and d.day == 21 and d.month == 12:
        notes.append("Solstizio d'inverno, il giorno più corto. ❄️")

    return DayInfo(
        iso=d.isoformat(),
        day_name_it=_DAYS_IT[d.weekday()],
        month_name_it=_MONTHS_IT[d.month - 1],
        long_format_it=long_fmt,
        week_number=week_num,
        is_weekend=d.weekday() >= 5,
        is_holiday=holiday is not None,
        holiday_name=holiday,
        season=season,
        saint=saint,
        moon_phase=moon_lbl,
        moon_phase_emoji=_MOON_EMOJI.get(moon_lbl, "🌒"),
        moon_illumination=moon_illum,
        sunrise=sunrise.strftime("%H:%M") if sunrise else None,
        sunset=sunset.strftime("%H:%M") if sunset else None,
        daylight_hours=round(daylight, 2) if daylight else None,
        proverb=_proverb_for(d),
        countdowns=_countdowns(d),
        notes=notes,
    )


def info_for_today(
    *, lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON
) -> DayInfo:
    return info_for(datetime.now(ROME).date(), lat=lat, lon=lon)


def info_to_dict(info: DayInfo) -> dict:
    return asdict(info)
