"""Weekly diet report — PDF + shareable Telegram message.

Builds the Monday→Sunday rollup, persists a `weekly_summaries` row, and
produces two outputs:
  * a printable branded PDF (CARA palette), and
  * a short text message formatted for the @cara_pedoto_bot Telegram bot.

There is no pre-existing PDF template in CARA to reuse, so this module
defines a small branded one (header + frequency table + disclaimer).
PDF generation degrades gracefully if reportlab is unavailable.

DISCLAIMER (mandatory, also rendered in UI): this module gives reminders
and suggestions, it is NOT a medical device; the source of truth is the
dietista's plan — for any doubt, refer to her.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.diet import PROTEIN_CATEGORIES, WeeklySummary
from cara.services import diet as diet_svc

log = structlog.get_logger(__name__)

REPORTS_DIR = Path("/app/uploads/diet/reports")

DISCLAIMER = (
    "Questo resoconto fornisce promemoria e suggerimenti, NON è un dispositivo "
    "medico. La fonte resta il piano della Dott.ssa Elena Poletti; per ogni "
    "dubbio rivolgersi a lei."
)

# CARA palette (matches the frontend design tokens).
_INK = (0.114, 0.125, 0.180)      # slate-900-ish
_ACCENT = (0.40, 0.36, 0.92)      # CARA violet
_MUTED = (0.45, 0.48, 0.55)

_STATE_EMOJI = {"ok": "✅", "under": "⚠️", "warn": "⚠️", "over": "❌"}


@dataclass
class WeeklyReport:
    week_start: date
    week_end: date
    pdf_path: str | None
    telegram_text: str
    adherence_score: float


def _fmt_target(rule) -> str:
    if rule is None:
        return "—"
    lo = int(rule.target_min) if rule.target_min is not None else None
    hi = int(rule.target_max) if rule.target_max is not None else None
    if lo is not None and hi is not None:
        return f"{lo}-{hi}" if lo != hi else f"{hi}"
    if hi is not None:
        return f"max {hi}"
    return "—"


def _build_rows(rollup, rules) -> list[dict]:
    rows = []
    for cat in PROTEIN_CATEGORIES:
        rule = rules.get(cat)
        consumed = rollup.consumed.get(cat, 0)
        state = diet_svc.category_state(consumed, rule)
        rows.append({
            "category": cat,
            "consumed": int(consumed),
            "target": _fmt_target(rule),
            "state": state,
            "emoji": _STATE_EMOJI.get(state, "✅"),
            "color": diet_svc.color_for(cat),
        })
    return rows


def format_telegram_text(rollup, rules, adherence: float, notes: list[str]) -> str:
    rows = _build_rows(rollup, rules)
    lines = [
        f"🍽️ <b>Resoconto settimana</b> {rollup.week_start.strftime('%d/%m')}–"
        f"{rollup.week_end.strftime('%d/%m')}",
        "",
        f"<b>Aderenza alle frequenze: {adherence:.0f}%</b>",
        "",
    ]
    for r in rows:
        lines.append(
            f"{r['emoji']} {r['category'].capitalize()}: "
            f"{r['consumed']} / {r['target']}"
        )
    extras = []
    if rollup.context_counts.get("pizza_piadina"):
        extras.append(f"🍕 pizza/piadina ×{rollup.context_counts['pizza_piadina']}")
    if rollup.context_counts.get("dolce"):
        extras.append(f"🍰 dolce ×{rollup.context_counts['dolce']}")
    if rollup.context_counts.get("aperitivo"):
        extras.append(f"🥂 aperitivo ×{rollup.context_counts['aperitivo']}")
    if extras:
        lines += ["", " · ".join(extras)]
    intake = []
    if rollup.avg_water_ml is not None:
        intake.append(f"💧 acqua media {rollup.avg_water_ml} ml/g")
    if rollup.avg_coffee is not None:
        intake.append(f"☕ caffè medi {rollup.avg_coffee}/g")
    if rollup.avg_kcal_per_day is not None:
        intake.append(f"≈ {rollup.avg_kcal_per_day} kcal/g (indicativo)")
    if intake:
        lines += ["", " · ".join(intake)]
    if notes:
        lines += [""] + [f"• {n}" for n in notes]
    lines += ["", f"<i>{DISCLAIMER}</i>"]
    return "\n".join(lines)


def _week_notes(rollup, rules) -> list[str]:
    notes: list[str] = []
    for cat in PROTEIN_CATEGORIES:
        rule = rules.get(cat)
        consumed = rollup.consumed.get(cat, 0)
        state = diet_svc.category_state(consumed, rule)
        if state == "over":
            notes.append(f"{cat.capitalize()} oltre il massimo: modera la prossima settimana.")
        elif state == "under":
            tmin = int(rule.target_min) if rule and rule.target_min else 0
            notes.append(f"{cat.capitalize()} sotto target ({int(consumed)}/{tmin}): da recuperare.")
    if rollup.days_logged < 5:
        notes.append(f"Solo {rollup.days_logged} giorni registrati: il dato è parziale.")
    return notes


def _render_pdf(path: Path, rollup, rules, adherence: float, notes: list[str]) -> bool:
    try:
        from reportlab.lib import colors  # noqa: PLC0415
        from reportlab.lib.pagesizes import A4  # noqa: PLC0415
        from reportlab.lib.units import mm  # noqa: PLC0415
        from reportlab.pdfgen import canvas  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        log.warning("diet.report.reportlab_missing", error=str(exc))
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    accent = colors.Color(*_ACCENT)
    ink = colors.Color(*_INK)
    muted = colors.Color(*_MUTED)

    # Header band.
    c.setFillColor(accent)
    c.rect(0, h - 32 * mm, w, 32 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20 * mm, h - 18 * mm, "CARA Nutrizione")
    c.setFont("Helvetica", 11)
    c.drawString(
        20 * mm, h - 26 * mm,
        f"Resoconto settimana {rollup.week_start.strftime('%d/%m/%Y')} – "
        f"{rollup.week_end.strftime('%d/%m/%Y')}",
    )

    y = h - 46 * mm
    c.setFillColor(ink)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, y, f"Aderenza alle frequenze: {adherence:.0f}%")
    y -= 12 * mm

    # Frequency table.
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(muted)
    c.drawString(20 * mm, y, "Categoria")
    c.drawString(85 * mm, y, "Consumato")
    c.drawString(120 * mm, y, "Target")
    c.drawString(150 * mm, y, "Stato")
    y -= 3 * mm
    c.setStrokeColor(muted)
    c.line(20 * mm, y, 190 * mm, y)
    y -= 7 * mm

    for r in _build_rows(rollup, rules):
        c.setFillColor(colors.Color(*[int(r["color"].lstrip("#")[i:i+2], 16) / 255 for i in (0, 2, 4)]))
        c.circle(22 * mm, y + 1.2 * mm, 1.8 * mm, fill=1, stroke=0)
        c.setFillColor(ink)
        c.setFont("Helvetica", 11)
        c.drawString(27 * mm, y, r["category"].capitalize())
        c.drawString(88 * mm, y, str(r["consumed"]))
        c.drawString(120 * mm, y, r["target"])
        label = {"ok": "in linea", "under": "sotto", "warn": "al limite", "over": "oltre"}[r["state"]]
        c.drawString(150 * mm, y, label)
        y -= 8 * mm

    # Intake line.
    y -= 4 * mm
    c.setFont("Helvetica", 10)
    c.setFillColor(muted)
    intake_bits = []
    if rollup.avg_water_ml is not None:
        intake_bits.append(f"Acqua media {rollup.avg_water_ml} ml/giorno")
    if rollup.avg_coffee is not None:
        intake_bits.append(f"Caffè medi {rollup.avg_coffee}/giorno")
    if rollup.avg_kcal_per_day is not None:
        intake_bits.append(f"≈ {rollup.avg_kcal_per_day} kcal/giorno (indicativo)")
    if intake_bits:
        c.drawString(20 * mm, y, "  ·  ".join(intake_bits))
        y -= 8 * mm

    # Notes.
    if notes:
        c.setFillColor(ink)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, "Note e suggerimenti")
        y -= 7 * mm
        c.setFont("Helvetica", 10)
        c.setFillColor(muted)
        for n in notes:
            c.drawString(22 * mm, y, f"• {n}")
            y -= 6 * mm

    # Disclaimer footer.
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(muted)
    _wrap_draw(c, DISCLAIMER, 20 * mm, 16 * mm, 170 * mm)
    c.showPage()
    c.save()
    return True


def _wrap_draw(c, text: str, x: float, y: float, max_w: float) -> None:
    from reportlab.pdfbase.pdfmetrics import stringWidth  # noqa: PLC0415

    words = text.split()
    line = ""
    # Draw wrapped lines bottom-up so the footer never collides: compute
    # the lines first, then place them with proper 10pt leading.
    lines: list[str] = []
    for word in words:
        trial = f"{line} {word}".strip()
        if stringWidth(trial, "Helvetica-Oblique", 8) > max_w:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    leading = 10
    start_y = y + (len(lines) - 1) * leading
    for i, ln in enumerate(lines):
        c.drawString(x, start_y - i * leading, ln)


async def build_weekly_report(
    session: AsyncSession,
    *,
    user_id: int,
    anchor: date | None = None,
    send_telegram: bool = False,
) -> WeeklyReport:
    anchor = anchor or diet_svc.rome_today()
    plan = await diet_svc.get_active_plan(session, user_id)
    rules = await diet_svc.get_rules(session, plan.id) if plan else {}
    rollup = await diet_svc.week_rollup(session, user_id, anchor)
    adherence = diet_svc.adherence_score(rollup.consumed, rules)
    notes = _week_notes(rollup, rules)

    pdf_path = REPORTS_DIR / f"{user_id}-{rollup.week_start.isoformat()}.pdf"
    ok = _render_pdf(pdf_path, rollup, rules, adherence, notes)
    pdf_str = str(pdf_path) if ok else None

    telegram_text = format_telegram_text(rollup, rules, adherence, notes)

    # Persist / upsert the weekly summary.
    existing = (
        await session.execute(
            select(WeeklySummary).where(
                WeeklySummary.user_id == user_id,
                WeeklySummary.week_start == rollup.week_start,
            )
        )
    ).scalar_one_or_none()
    totals = {
        "consumed": rollup.consumed,
        "context_counts": rollup.context_counts,
        "avg_kcal_per_day": rollup.avg_kcal_per_day,
        "avg_water_ml": rollup.avg_water_ml,
        "avg_coffee": rollup.avg_coffee,
        "days_logged": rollup.days_logged,
    }
    if existing is None:
        session.add(WeeklySummary(
            user_id=user_id,
            week_start=rollup.week_start,
            week_end=rollup.week_end,
            totals=totals,
            adherence_score=adherence,
            report_pdf_path=pdf_str,
        ))
    else:
        existing.totals = totals
        existing.adherence_score = adherence
        existing.week_end = rollup.week_end
        if pdf_str:
            existing.report_pdf_path = pdf_str
    await session.commit()

    if send_telegram:
        await _send_telegram(telegram_text)

    return WeeklyReport(
        week_start=rollup.week_start,
        week_end=rollup.week_end,
        pdf_path=pdf_str,
        telegram_text=telegram_text,
        adherence_score=adherence,
    )


async def _send_telegram(text: str) -> bool:
    """Fan-out the report via the family bus → Telegram (best-effort)."""
    try:
        from cara.services.notify import Notification, enqueue_for_backend  # noqa: PLC0415

        await enqueue_for_backend(Notification(
            kind="diet.weekly_report",
            title="Resoconto settimanale dieta",
            body=text,
            tag="diet-weekly",
        ))
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("diet.report.telegram_failed", error=str(exc))
        return False
