"""REST API per le info giornaliere del calendario italiano.

Endpoint:
    GET /api/v1/calendar/day-info?date=YYYY-MM-DD (default oggi)
    GET /api/v1/calendar/month-info?year=YYYY&month=MM (riepilogo mese)
    GET /api/v1/calendar/year-holidays?year=YYYY (lista feste italiane anno)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cara.api.deps import get_current_user
from cara.models import User
from cara.services import daily_info as daily_svc


router = APIRouter(prefix="/calendar", tags=["calendar-info"])


class DayInfoOut(BaseModel):
    iso: str
    day_name_it: str
    month_name_it: str
    long_format_it: str
    week_number: int
    is_weekend: bool
    is_holiday: bool
    holiday_name: str | None
    season: str
    saint: str | None
    moon_phase: str
    moon_phase_emoji: str
    moon_illumination: float
    sunrise: str | None
    sunset: str | None
    daylight_hours: float | None
    proverb: str
    countdowns: list[dict[str, Any]]
    notes: list[str]


@router.get("/day-info", response_model=DayInfoOut)
async def day_info(
    date_iso: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    user: User = Depends(get_current_user),  # noqa: B008
) -> DayInfoOut:
    """Info complete per una data (default oggi Europe/Rome).

    Riferimento posizione: Ferrara (44.838, 11.621) se lat/lon non
    passati. Per altre città passare lat/lon come query.
    """
    try:
        d = date.fromisoformat(date_iso) if date_iso else None
    except ValueError as exc:
        raise HTTPException(400, "date_iso deve essere YYYY-MM-DD") from exc

    info = (
        daily_svc.info_for(d, lat=lat or daily_svc.DEFAULT_LAT, lon=lon or daily_svc.DEFAULT_LON)
        if d
        else daily_svc.info_for_today(lat=lat or daily_svc.DEFAULT_LAT, lon=lon or daily_svc.DEFAULT_LON)
    )
    return DayInfoOut.model_validate(daily_svc.info_to_dict(info))


class HolidayOut(BaseModel):
    date: str
    label: str
    fixed: bool


@router.get("/year-holidays", response_model=list[HolidayOut])
async def year_holidays(
    year: int | None = None,
    user: User = Depends(get_current_user),  # noqa: B008
) -> list[HolidayOut]:
    """Festività italiane dell'anno specificato (default = corrente)."""
    y = year or datetime.now(daily_svc.ROME).year
    out: list[HolidayOut] = []

    # Fixed
    for (m, d), label in daily_svc._FIXED_HOLIDAYS.items():  # noqa: SLF001
        out.append(HolidayOut(date=date(y, m, d).isoformat(), label=label, fixed=True))

    # Movable
    easter = daily_svc._easter_sunday(y)  # noqa: SLF001
    out.append(HolidayOut(date=easter.isoformat(), label="Pasqua", fixed=False))
    import datetime as _dt

    out.append(
        HolidayOut(
            date=(easter + _dt.timedelta(days=1)).isoformat(),
            label="Pasquetta",
            fixed=False,
        )
    )
    out.append(
        HolidayOut(
            date=(easter - _dt.timedelta(days=2)).isoformat(),
            label="Venerdì Santo",
            fixed=False,
        )
    )

    out.sort(key=lambda h: h.date)
    return out


class MonthSummaryOut(BaseModel):
    year: int
    month: int
    month_name_it: str
    days_total: int
    holidays: list[HolidayOut]
    week_count: int
    moon_events: list[dict[str, Any]]


@router.get("/month-info", response_model=MonthSummaryOut)
async def month_info(
    year: int | None = None,
    month: int | None = None,
    user: User = Depends(get_current_user),  # noqa: B008
) -> MonthSummaryOut:
    """Riepilogo mese: festività + eventi lunari (nuova, piena)."""
    now = datetime.now(daily_svc.ROME).date()
    y = year or now.year
    m = month or now.month
    if not 1 <= m <= 12:
        raise HTTPException(400, "month deve essere fra 1 e 12")

    # Holidays nel mese
    holidays: list[HolidayOut] = []
    for (hm, hd), label in daily_svc._FIXED_HOLIDAYS.items():  # noqa: SLF001
        if hm == m:
            holidays.append(
                HolidayOut(date=date(y, hm, hd).isoformat(), label=label, fixed=True)
            )
    easter = daily_svc._easter_sunday(y)  # noqa: SLF001
    import datetime as _dt
    for ev_date, lbl in (
        (easter, "Pasqua"),
        (easter + _dt.timedelta(days=1), "Pasquetta"),
        (easter - _dt.timedelta(days=2), "Venerdì Santo"),
    ):
        if ev_date.month == m and ev_date.year == y:
            holidays.append(
                HolidayOut(date=ev_date.isoformat(), label=lbl, fixed=False)
            )
    holidays.sort(key=lambda h: h.date)

    # Moon events
    from calendar import monthrange  # noqa: PLC0415

    last_day = monthrange(y, m)[1]
    moon_events: list[dict[str, Any]] = []
    prev_phase: str | None = None
    for d_num in range(1, last_day + 1):
        dd = date(y, m, d_num)
        phase, _ = daily_svc._moon_phase(dd)  # noqa: SLF001
        if phase != prev_phase and phase in {
            "luna nuova", "primo quarto", "luna piena", "ultimo quarto"
        }:
            moon_events.append({
                "date": dd.isoformat(),
                "phase": phase,
                "emoji": daily_svc._MOON_EMOJI.get(phase, ""),  # noqa: SLF001
            })
        prev_phase = phase

    return MonthSummaryOut(
        year=y,
        month=m,
        month_name_it=daily_svc._MONTHS_IT[m - 1],  # noqa: SLF001
        days_total=last_day,
        holidays=holidays,
        week_count=4 + (last_day - 28 > 0),
        moon_events=moon_events,
    )
