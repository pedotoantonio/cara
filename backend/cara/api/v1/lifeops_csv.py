"""LifeOps M3 — Import CSV bancario + Export CSV commercialista.

Endpoint:
    POST   /api/v1/lifeops/finance/import-csv (multipart, ?commit=false)
    GET    /api/v1/lifeops/finance/export.csv?from_iso=&to_iso=

Formati supportati per l'import:
- Unicredit (Data, Causale, Importo, Saldo)
- Intesa (Data Contabile, Data Operazione, Descrizione, Importo)
- N26 / Revolut (Date, Description, Amount, Currency)
- Generico (Date|Data, Description|Descrizione|Causale, Amount|Importo)

Detection automatica della colonna importo + segno (negativo = expense,
positivo = income). Classificazione categoria via lifeops.intent_router
helper `_classify_finance_category`.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models import (
    LifeopsAccount,
    LifeopsFinanceCategory,
    LifeopsTransaction,
    User,
)
from cara.store import get_session


log = structlog.get_logger(__name__)
router = APIRouter(prefix="/lifeops/finance", tags=["lifeops-finance-csv"])


# ─── Heuristics column detection ─────────────────────────────────────


_DATE_KEYS = (
    "data",
    "data contabile",
    "data operazione",
    "data valuta",
    "date",
    "data oper.",
)
_AMOUNT_KEYS = (
    "importo",
    "amount",
    "movimento",
    "valore",
    "addebito",
    "accredito",
)
_DESC_KEYS = (
    "descrizione",
    "causale",
    "description",
    "merchant",
    "operazione",
    "memo",
)


def _normalize_key(s: str) -> str:
    return s.strip().lower().replace("_", " ").replace("-", " ")


def _detect_col(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    nmap = {_normalize_key(f): f for f in fieldnames}
    for cand in candidates:
        for nk, orig in nmap.items():
            if cand in nk:
                return orig
    return None


def _parse_amount(raw: str) -> Decimal | None:
    s = raw.strip().replace("€", "").replace("EUR", "").strip()
    # Negative sign in brackets sometimes used in IT bank exports
    is_negative = False
    if s.startswith("-"):
        is_negative = True
        s = s[1:].strip()
    elif s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()
    # Italian format: "1.234,56" → "1234.56"
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        val = Decimal(s).quantize(Decimal("0.01"))
        return -val if is_negative else val
    except (InvalidOperation, ValueError):
        return None


def _parse_date(raw: str) -> datetime | None:
    s = raw.strip()
    for fmt in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%Y/%m/%d",
        "%d/%m/%y",
    ):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _classify_category(description: str) -> str | None:
    from cara.lifeops.intent_router import _classify_finance_category  # noqa: PLC0415
    return _classify_finance_category(description)


# ─── Schemas ─────────────────────────────────────────────────────────


class ImportPreviewRow(BaseModel):
    happened_at: datetime
    amount: str
    direction: str
    description: str
    category_slug: str | None


class ImportPreview(BaseModel):
    parsed_rows: int
    skipped_rows: int
    rows: list[ImportPreviewRow]
    detected_columns: dict[str, str | None]


class ImportResult(BaseModel):
    inserted: int
    skipped: int


# ─── Import CSV ──────────────────────────────────────────────────────


@router.post("/import-csv", response_model=dict[str, Any])
async def import_csv(
    file: UploadFile = File(...),  # noqa: B008
    commit: bool = False,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Import transactions da CSV bancario.

    - `commit=false` (default) → dry-run, ritorna preview
    - `commit=true`            → inserisci come state='pending' (l'utente
                                  conferma in UI)
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "file vuoto")

    # Decode con fallback latin1 (le banche italiane spesso usano CP1252)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin1", errors="replace")

    # Detect separator
    first_line = text.split("\n", 1)[0] if text else ""
    separator = ";" if first_line.count(";") > first_line.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=separator)
    fieldnames = reader.fieldnames or []
    if not fieldnames:
        raise HTTPException(400, "CSV senza header")

    date_col = _detect_col(fieldnames, _DATE_KEYS)
    amount_col = _detect_col(fieldnames, _AMOUNT_KEYS)
    desc_col = _detect_col(fieldnames, _DESC_KEYS)
    if not (date_col and amount_col):
        raise HTTPException(
            400,
            f"Impossibile identificare colonne data/importo. "
            f"Trovate: {fieldnames}",
        )

    # Pre-load categorie + account
    cat_stmt = select(LifeopsFinanceCategory).where(
        LifeopsFinanceCategory.family_id.is_(None)
    )
    categories = (await session.execute(cat_stmt)).scalars().all()
    cat_by_slug = {c.slug: c for c in categories}

    acc_stmt = (
        select(LifeopsAccount)
        .where(
            LifeopsAccount.user_id == user.id,
            LifeopsAccount.deleted_at.is_(None),
        )
        .order_by(LifeopsAccount.created_at.asc())
        .limit(1)
    )
    account = (await session.execute(acc_stmt)).scalar_one_or_none()
    if account is None:
        # Crea Bancario default
        account = LifeopsAccount(
            user_id=user.id, name="Bancario (CSV)", kind="bank", currency="EUR"
        )
        session.add(account)
        await session.flush()

    preview_rows: list[ImportPreviewRow] = []
    skipped = 0
    inserted = 0
    for row in reader:
        happened_at = _parse_date(row.get(date_col, "") or "")
        amount = _parse_amount(row.get(amount_col, "") or "")
        description = (row.get(desc_col, "") if desc_col else "") or ""
        if happened_at is None or amount is None:
            skipped += 1
            continue
        if amount == 0:
            skipped += 1
            continue
        direction = "expense" if amount < 0 else "income"
        amount_abs = abs(amount)
        category_slug = _classify_category(description)

        preview_rows.append(
            ImportPreviewRow(
                happened_at=happened_at,
                amount=str(amount_abs),
                direction=direction,
                description=description[:280] or "Import CSV",
                category_slug=category_slug,
            )
        )

        if commit:
            tx = LifeopsTransaction(
                user_id=user.id,
                account_id=account.id,
                category_id=cat_by_slug[category_slug].id
                if category_slug and category_slug in cat_by_slug
                else None,
                amount=amount_abs,
                direction=direction,
                happened_at=happened_at,
                description=description[:280] or "Import CSV",
                state="pending",  # utente conferma in UI dopo import
            )
            session.add(tx)
            inserted += 1

    if commit:
        await session.flush()

    return {
        "preview": ImportPreview(
            parsed_rows=len(preview_rows),
            skipped_rows=skipped,
            rows=preview_rows[:50],  # cap preview a 50 righe per UI
            detected_columns={
                "date": date_col,
                "amount": amount_col,
                "description": desc_col,
            },
        ).model_dump(mode="json"),
        "committed": commit,
        "inserted": inserted if commit else 0,
    }


# ─── Export CSV commercialista ───────────────────────────────────────


@router.get("/export.csv")
async def export_csv(
    from_iso: str | None = None,
    to_iso: str | None = None,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> StreamingResponse:
    """Export delle transazioni confermate in formato CSV standard.

    Columns: Data; Importo; Tipo; Categoria; Descrizione

    Format italiano: '1.234,56' per gli importi, ';' come separator.
    """
    stmt = select(LifeopsTransaction).where(
        LifeopsTransaction.user_id == user.id,
        LifeopsTransaction.state == "confirmed",
        LifeopsTransaction.deleted_at.is_(None),
    )
    if from_iso:
        stmt = stmt.where(LifeopsTransaction.happened_at >= datetime.fromisoformat(from_iso))
    if to_iso:
        stmt = stmt.where(LifeopsTransaction.happened_at <= datetime.fromisoformat(to_iso))
    stmt = stmt.order_by(LifeopsTransaction.happened_at.asc())
    rows = (await session.execute(stmt)).scalars().all()

    cat_stmt = select(LifeopsFinanceCategory)
    cats = (await session.execute(cat_stmt)).scalars().all()
    cat_by_id = {c.id: c for c in cats}

    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(["Data", "Importo", "Tipo", "Categoria", "Descrizione"])
    for tx in rows:
        amount_fmt = f"{tx.amount:.2f}".replace(".", ",")
        cat_label = (
            cat_by_id[tx.category_id].label if tx.category_id in cat_by_id else ""
        )
        writer.writerow(
            [
                tx.happened_at.strftime("%d/%m/%Y"),
                amount_fmt,
                "Spesa" if tx.direction == "expense" else "Entrata",
                cat_label,
                (tx.description or "")[:280],
            ]
        )

    out.seek(0)
    filename = f"cara_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([out.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
