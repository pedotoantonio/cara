"""File ingestion service: store blob + extract text + persist row.

Supported document kinds:
    - pdf  → pypdf
    - docx → python-docx
    - xlsx → openpyxl  (per-sheet text dump)
    - csv  → naive parse (first 200 rows joined as TSV-ish text)
    - md / txt / json / yaml / yml → read as utf-8
    - other → metadata only, no text extraction (returned as kind="other")

Storage: blobs are written to `/app/data/uploads/<sha256[:2]>/<sha256>`.
The same content uploaded twice deduplicates by hash but each user keeps
their own row (so "delete file" only removes their record, not the blob).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models import UploadedFile

logger = structlog.get_logger(__name__)

UPLOADS_ROOT = Path("/app/data/uploads")
MAX_FILE_BYTES = 25 * 1024 * 1024   # 25 MB hard cap
MAX_TEXT_CHARS = 100_000             # cap text storage; longer files are truncated

# Default summary length when injecting into chat prompts.
DEFAULT_SUMMARY_CHARS = 800


def _kind_from_mime(filename: str, mime: str) -> str:
    name = (filename or "").lower()
    m = (mime or "").lower()
    if name.endswith(".pdf") or "pdf" in m:
        return "pdf"
    if name.endswith(".docx") or "wordprocessingml" in m:
        return "docx"
    if name.endswith(".xlsx") or "spreadsheetml" in m:
        return "xlsx"
    if name.endswith(".csv") or m == "text/csv":
        return "csv"
    if name.endswith((".txt", ".md", ".json", ".yaml", ".yml")) or m.startswith("text/"):
        return "text"
    return "other"


def _extract_pdf(blob: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(blob))
        parts: list[str] = []
        for page in reader.pages[:200]:  # cap at 200 pages to bound work
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - best effort per page
                continue
        return "\n\n".join(p.strip() for p in parts if p.strip())
    except Exception as exc:  # noqa: BLE001
        logger.warning("files.pdf_extract_failed", error=str(exc))
        return ""


def _extract_docx(blob: bytes) -> str:
    from docx import Document

    try:
        doc = Document(io.BytesIO(blob))
        return "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("files.docx_extract_failed", error=str(exc))
        return ""


def _extract_xlsx(blob: bytes) -> str:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
        out: list[str] = []
        for sheet in wb.sheetnames[:20]:
            ws = wb[sheet]
            out.append(f"=== Foglio: {sheet} ===")
            for row in ws.iter_rows(max_rows=500, values_only=True):
                cells = ["" if c is None else str(c) for c in row]
                if any(cells):
                    out.append("\t".join(cells))
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("files.xlsx_extract_failed", error=str(exc))
        return ""


def _extract_csv(blob: bytes) -> str:
    try:
        text = blob.decode("utf-8", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))[:500]
        return "\n".join("\t".join(r) for r in rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("files.csv_extract_failed", error=str(exc))
        return ""


def _extract_text(blob: bytes) -> str:
    try:
        return blob.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def extract_text(kind: str, blob: bytes) -> str:
    if kind == "pdf":
        text = _extract_pdf(blob)
    elif kind == "docx":
        text = _extract_docx(blob)
    elif kind == "xlsx":
        text = _extract_xlsx(blob)
    elif kind == "csv":
        text = _extract_csv(blob)
    elif kind == "text":
        text = _extract_text(blob)
    else:
        text = ""
    return text[:MAX_TEXT_CHARS]


def _summary_of(text: str, max_chars: int = DEFAULT_SUMMARY_CHARS) -> str:
    """Cheap summary: first N characters, snapped to a paragraph boundary."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text.strip()
    cut = text[:max_chars]
    last_break = max(cut.rfind("\n\n"), cut.rfind(". "))
    if last_break > max_chars * 0.5:
        cut = cut[: last_break + 1]
    return cut.strip() + "\n…"


def _store_blob(blob: bytes, sha256: str) -> Path:
    UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)
    sub = UPLOADS_ROOT / sha256[:2]
    sub.mkdir(exist_ok=True)
    path = sub / sha256
    if not path.exists():
        path.write_bytes(blob)
    return path


async def ingest_blob(
    session: AsyncSession,
    *,
    user_id: int,
    filename: str,
    mime_type: str,
    blob: bytes,
) -> UploadedFile:
    if len(blob) > MAX_FILE_BYTES:
        raise ValueError(f"file too large: {len(blob)} > {MAX_FILE_BYTES}")
    sha = hashlib.sha256(blob).hexdigest()
    path = _store_blob(blob, sha)
    kind = _kind_from_mime(filename, mime_type)
    text = extract_text(kind, blob)
    summary = _summary_of(text)
    metadata: dict[str, Any] = {"text_chars": len(text)}
    row = UploadedFile(
        user_id=user_id,
        filename=filename,
        mime_type=mime_type or "application/octet-stream",
        kind=kind,
        size_bytes=len(blob),
        sha256=sha,
        storage_path=str(path),
        text_content=text or None,
        summary=summary or None,
        metadata_json=metadata,
    )
    session.add(row)
    await session.flush()
    return row


async def get_file(
    session: AsyncSession, file_id: uuid.UUID, *, user_id: int
) -> UploadedFile | None:
    stmt = select(UploadedFile).where(
        UploadedFile.id == file_id, UploadedFile.user_id == user_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_files(session: AsyncSession, *, user_id: int, limit: int = 50) -> list[UploadedFile]:
    stmt = (
        select(UploadedFile)
        .where(UploadedFile.user_id == user_id)
        .order_by(UploadedFile.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def delete_file(
    session: AsyncSession, file_id: uuid.UUID, *, user_id: int
) -> bool:
    row = await get_file(session, file_id, user_id=user_id)
    if row is None:
        return False
    # Remove the row only — keep the blob, other users may share it via hash.
    await session.delete(row)
    return True


async def files_by_ids(
    session: AsyncSession, ids: list[uuid.UUID], *, user_id: int
) -> list[UploadedFile]:
    if not ids:
        return []
    stmt = select(UploadedFile).where(
        UploadedFile.id.in_(ids), UploadedFile.user_id == user_id
    )
    return list((await session.execute(stmt)).scalars().all())


def files_to_prompt_block(files: list[UploadedFile]) -> str:
    """Render a compact, model-friendly block to inject into the chat prompt.

    Phrased to fight the very common 1.5B refusal pattern ("I cannot access
    attachments"): the wrapper tells the model the text IS already in front
    of it, so it must use it as the primary source instead of refusing.
    """
    if not files:
        return ""
    parts = [
        "[CONTENUTO DEI FILE — è già stato letto ed è qui sotto. "
        "Rispondi alla domanda dell'utente usando questo testo come fonte. "
        "NON dire 'non posso accedere ai file': il testo è già davanti a te.]"
    ]
    for f in files:
        head = f"--- File: {f.filename} ({f.kind}, {f.size_bytes // 1024} KB) ---"
        body = (f.summary or f.text_content or "(nessun testo estratto)")[:DEFAULT_SUMMARY_CHARS]
        parts.append(f"{head}\n{body}")
    return "\n\n".join(parts)


def has_extractable_text(f: UploadedFile) -> bool:
    """True if extraction produced enough usable text to feed the model."""
    return bool(f.text_content and len(f.text_content.strip()) >= 20)


__all__ = [
    "delete_file",
    "files_by_ids",
    "files_to_prompt_block",
    "has_extractable_text",
    "get_file",
    "ingest_blob",
    "list_files",
]


def __dir__() -> list[str]:
    return list(__all__) + ["json"]


_ = json  # keep import so feedparser-style optional helpers can re-use it
