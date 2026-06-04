"""Energy / calorie logic for CARA Nutrizione.

Formulas (validated, see WebSearch notes in the diet module docs):
  * BMR  — Mifflin-St Jeor (1990):
        man:   10·kg + 6.25·cm − 5·age + 5
        woman: 10·kg + 6.25·cm − 5·age − 161
  * TDEE — BMR × activity factor (1.2 … 1.9)
  * daily target — TDEE + goal delta (deficit/surplus)
  * exercise kcal — MET × weight_kg × hours   (1 MET = 1 kcal/kg/h)
  * remaining — target − consumed + burned    (no double-count: the
        activity factor covers baseline lifestyle, logged sport adds on top)

Calories stay a SECONDARY metric in this module; frequencies are primary.
All stats are computed on demand (real-time) over day/week/month/year,
bucketed in Europe/Rome local days.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.diet import (
    ACTIVITY_FACTORS,
    GOAL_DEFAULT_DELTA,
    DietProfile,
    ExerciseLog,
    MealLog,
)
from cara.services.diet import ROME, rome_today, week_bounds

log = structlog.get_logger(__name__)

# ─── MET catalog (Compendium of Physical Activities, common items) ──
# Each: slug, Italian label, MET, intensity bucket. Exposed via the API
# so the client can pick an activity and auto-fill the MET.
MET_CATALOG: list[dict] = [
    {"slug": "camminata_lenta", "label": "Camminata lenta (3 km/h)", "met": 2.8, "intensity": "leggera"},
    {"slug": "camminata_veloce", "label": "Camminata veloce (5-6 km/h)", "met": 4.3, "intensity": "moderata"},
    {"slug": "corsa_lenta", "label": "Corsa lenta (8 km/h)", "met": 8.3, "intensity": "intensa"},
    {"slug": "corsa", "label": "Corsa (10 km/h)", "met": 9.8, "intensity": "intensa"},
    {"slug": "bici_moderata", "label": "Bicicletta moderata (16-19 km/h)", "met": 6.8, "intensity": "moderata"},
    {"slug": "bici_intensa", "label": "Bicicletta intensa (>19 km/h)", "met": 10.0, "intensity": "intensa"},
    {"slug": "nuoto_moderato", "label": "Nuoto moderato", "met": 5.8, "intensity": "moderata"},
    {"slug": "nuoto_intenso", "label": "Nuoto intenso", "met": 9.8, "intensity": "intensa"},
    {"slug": "pesi_moderato", "label": "Palestra / pesi (moderato)", "met": 3.5, "intensity": "moderata"},
    {"slug": "pesi_vigoroso", "label": "Palestra / pesi (vigoroso)", "met": 6.0, "intensity": "intensa"},
    {"slug": "crossfit", "label": "CrossFit / HIIT", "met": 8.0, "intensity": "intensa"},
    {"slug": "yoga", "label": "Yoga", "met": 2.5, "intensity": "leggera"},
    {"slug": "pilates", "label": "Pilates", "met": 3.0, "intensity": "leggera"},
    {"slug": "calcio", "label": "Calcio", "met": 7.0, "intensity": "intensa"},
    {"slug": "tennis", "label": "Tennis", "met": 7.3, "intensity": "intensa"},
    {"slug": "padel", "label": "Padel", "met": 6.0, "intensity": "moderata"},
    {"slug": "pallavolo", "label": "Pallavolo", "met": 4.0, "intensity": "moderata"},
    {"slug": "basket", "label": "Basket", "met": 6.5, "intensity": "intensa"},
    {"slug": "sci", "label": "Sci", "met": 7.0, "intensity": "intensa"},
    {"slug": "trekking", "label": "Escursionismo / trekking", "met": 6.0, "intensity": "moderata"},
    {"slug": "ellittica", "label": "Ellittica", "met": 5.0, "intensity": "moderata"},
    {"slug": "cyclette", "label": "Cyclette", "met": 6.8, "intensity": "moderata"},
    {"slug": "spinning", "label": "Spinning", "met": 8.5, "intensity": "intensa"},
    {"slug": "aerobica", "label": "Aerobica", "met": 7.3, "intensity": "intensa"},
    {"slug": "ballo", "label": "Ballo", "met": 5.0, "intensity": "moderata"},
    {"slug": "corda", "label": "Salto con la corda", "met": 11.0, "intensity": "intensa"},
    {"slug": "vogatore", "label": "Canottaggio / vogatore", "met": 7.0, "intensity": "intensa"},
    {"slug": "arti_marziali", "label": "Arti marziali", "met": 10.3, "intensity": "intensa"},
    {"slug": "scale", "label": "Salire le scale", "met": 8.0, "intensity": "intensa"},
    {"slug": "giardinaggio", "label": "Giardinaggio", "met": 3.8, "intensity": "moderata"},
    {"slug": "pulizie", "label": "Pulizie domestiche", "met": 3.3, "intensity": "leggera"},
]

_MET_BY_SLUG = {m["slug"]: m for m in MET_CATALOG}


# ─── Pure formulas ─────────────────────────────────────────────────


def age_from(birth_date: date | None, on: date | None = None) -> int | None:
    if birth_date is None:
        return None
    on = on or rome_today()
    return on.year - birth_date.year - (
        (on.month, on.day) < (birth_date.month, birth_date.day)
    )


def compute_bmr(profile: DietProfile) -> float | None:
    """Mifflin-St Jeor. None if the profile lacks required fields."""
    age = age_from(profile.birth_date)
    if not (profile.weight_kg and profile.height_cm and age and profile.sex):
        return None
    base = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * age
    if profile.sex.upper() == "M":
        return base + 5
    if profile.sex.upper() == "F":
        return base - 161
    return None


def compute_tdee(profile: DietProfile) -> float | None:
    bmr = compute_bmr(profile)
    if bmr is None:
        return None
    factor = ACTIVITY_FACTORS.get(profile.activity_level, 1.55)
    return bmr * factor


def daily_target(profile: DietProfile) -> int | None:
    tdee = compute_tdee(profile)
    if tdee is None:
        return None
    delta = (
        profile.goal_rate_kcal
        if profile.goal_rate_kcal is not None
        else GOAL_DEFAULT_DELTA.get(profile.goal, 0)
    )
    return round(tdee + delta)


def exercise_kcal(met: float, weight_kg: float | None, duration_min: int) -> int:
    """MET × weight(kg) × hours. Falls back to 70 kg if weight unknown."""
    w = weight_kg or 70.0
    return round(met * w * (duration_min / 60.0))


# ─── Period helpers ────────────────────────────────────────────────


def period_bounds(period: str, anchor: date) -> tuple[date, date]:
    if period == "day":
        return anchor, anchor
    if period == "week":
        return week_bounds(anchor)
    if period == "month":
        last = calendar.monthrange(anchor.year, anchor.month)[1]
        return anchor.replace(day=1), anchor.replace(day=last)
    if period == "year":
        return date(anchor.year, 1, 1), date(anchor.year, 12, 31)
    return anchor, anchor


def _day_range_utc(start: date, end: date) -> tuple[datetime, datetime]:
    s = datetime.combine(start, time.min, tzinfo=ROME).astimezone(UTC)
    e = datetime.combine(end, time.max, tzinfo=ROME).astimezone(UTC)
    return s, e


@dataclass
class EnergyStats:
    period: str
    period_start: date
    period_end: date
    profile_complete: bool
    bmr: int | None
    tdee: int | None
    daily_target: int | None
    days_elapsed: int
    consumed: int
    burned: int
    net: int                          # consumed − burned
    target_total: int | None          # daily_target × days_elapsed
    remaining: int | None             # target_total − consumed + burned
    avg_consumed_per_day: int
    avg_burned_per_day: int
    breakdown: list[dict] = field(default_factory=list)


async def energy_stats(
    session: AsyncSession, *, user_id: int, period: str = "day", anchor: date | None = None
) -> EnergyStats:
    anchor = anchor or rome_today()
    if period not in ("day", "week", "month", "year"):
        period = "day"
    start, end = period_bounds(period, anchor)
    today = rome_today()
    # Count only elapsed days for the current/ongoing period.
    eff_end = min(end, today) if start <= today <= end else end
    days_elapsed = max(1, (eff_end - start).days + 1) if start <= today else (end - start).days + 1

    profile = (
        await session.execute(
            select(DietProfile).where(DietProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    tgt = daily_target(profile) if profile else None
    bmr = compute_bmr(profile) if profile else None
    tdee = compute_tdee(profile) if profile else None
    complete = tgt is not None

    s_utc, e_utc = _day_range_utc(start, end)
    meals = list(
        (
            await session.execute(
                select(MealLog).where(
                    MealLog.user_id == user_id,
                    MealLog.logged_at >= s_utc,
                    MealLog.logged_at <= e_utc,
                )
            )
        ).scalars().all()
    )
    exercises = list(
        (
            await session.execute(
                select(ExerciseLog).where(
                    ExerciseLog.user_id == user_id,
                    ExerciseLog.logged_at >= s_utc,
                    ExerciseLog.logged_at <= e_utc,
                )
            )
        ).scalars().all()
    )

    # Bucket by Rome-local day (year → monthly buckets to keep it small).
    by_day_consumed: dict[date, int] = {}
    by_day_burned: dict[date, int] = {}
    for m in meals:
        if m.est_kcal:
            d = m.logged_at.astimezone(ROME).date()
            by_day_consumed[d] = by_day_consumed.get(d, 0) + m.est_kcal
    for x in exercises:
        d = x.logged_at.astimezone(ROME).date()
        by_day_burned[d] = by_day_burned.get(d, 0) + x.kcal_burned

    consumed = sum(by_day_consumed.values())
    burned = sum(by_day_burned.values())
    target_total = tgt * days_elapsed if tgt is not None else None
    remaining = (target_total - consumed + burned) if target_total is not None else None

    breakdown = _build_breakdown(period, start, end, by_day_consumed, by_day_burned, tgt)

    return EnergyStats(
        period=period,
        period_start=start,
        period_end=end,
        profile_complete=complete,
        bmr=round(bmr) if bmr else None,
        tdee=round(tdee) if tdee else None,
        daily_target=tgt,
        days_elapsed=days_elapsed,
        consumed=consumed,
        burned=burned,
        net=consumed - burned,
        target_total=target_total,
        remaining=remaining,
        avg_consumed_per_day=round(consumed / days_elapsed),
        avg_burned_per_day=round(burned / days_elapsed),
        breakdown=breakdown,
    )


def _build_breakdown(
    period: str,
    start: date,
    end: date,
    consumed: dict[date, int],
    burned: dict[date, int],
    daily_tgt: int | None,
) -> list[dict]:
    """Per-day buckets (day→1, week→7, month→~30), per-month for year (12)."""
    out: list[dict] = []
    if period == "year":
        for month in range(1, 13):
            m_start = date(start.year, month, 1)
            m_end = date(start.year, month, calendar.monthrange(start.year, month)[1])
            c = sum(v for d, v in consumed.items() if m_start <= d <= m_end)
            b = sum(v for d, v in burned.items() if m_start <= d <= m_end)
            ndays = (m_end - m_start).days + 1
            out.append({
                "label": f"{month:02d}",
                "start": m_start.isoformat(),
                "consumed": c,
                "burned": b,
                "target": daily_tgt * ndays if daily_tgt else None,
            })
        return out
    d = start
    while d <= end:
        out.append({
            "label": d.strftime("%d/%m") if period != "day" else d.isoformat(),
            "start": d.isoformat(),
            "consumed": consumed.get(d, 0),
            "burned": burned.get(d, 0),
            "target": daily_tgt,
        })
        d += timedelta(days=1)
    return out


# ─── Exercise CRUD helpers ─────────────────────────────────────────


async def log_exercise(
    session: AsyncSession,
    *,
    user_id: int,
    activity: str,
    met: float,
    duration_min: int,
    logged_at: datetime | None = None,
    notes: str | None = None,
) -> ExerciseLog:
    profile = (
        await session.execute(
            select(DietProfile).where(DietProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    weight = profile.weight_kg if profile else None
    kcal = exercise_kcal(met, weight, duration_min)
    row = ExerciseLog(
        user_id=user_id,
        logged_at=logged_at or datetime.now(UTC),
        activity=activity,
        met=met,
        duration_min=duration_min,
        kcal_burned=kcal,
        notes=notes,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def exercises_on_day(
    session: AsyncSession, user_id: int, day: date
) -> list[ExerciseLog]:
    s, e = _day_range_utc(day, day)
    return list(
        (
            await session.execute(
                select(ExerciseLog)
                .where(
                    ExerciseLog.user_id == user_id,
                    ExerciseLog.logged_at >= s,
                    ExerciseLog.logged_at <= e,
                )
                .order_by(ExerciseLog.logged_at)
            )
        ).scalars().all()
    )


def met_for_slug(slug: str) -> dict | None:
    return _MET_BY_SLUG.get(slug)
