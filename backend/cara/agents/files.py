"""Files agent — on-demand PDF / DOCX / image ingestion + OCR.

Triggered from `POST /api/v1/files`: the API stores the blob, inserts
a row with status=pending, returns 202, and enqueues `ingest_file`.
This task reads the blob from disk, runs the appropriate extractor,
writes text + summary back to the same row, and flips status to
`ready` (or `failed`). Heavy parses (50-page PDFs, high-res photos)
no longer block the chat orchestrator.

The task is idempotent: `idempotency_key=str(file_id)` so a
double-trigger only runs once. Re-running on an already-`ready` row
re-extracts (useful when the parser is upgraded).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from cara.agents._base import _get_sessionmaker, cara_task
from cara.services.files import extract_into_row


log = structlog.get_logger(__name__)


@cara_task(agent="files")
async def ingest_file(
    file_id: str,
    user_id: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Re-parse + index an uploaded file.

    Args:
        file_id: UUID of the row in `files` table (string for JSON
            serialisation in the Celery payload).
        user_id: owner user id (passed for logging and future
            permission checks; service layer scopes by user_id at the
            chat read path, not at extraction).
        idempotency_key: defaults to `file:<file_id>` so re-triggers
            of the same upload short-circuit.
    """
    sessionmaker = _get_sessionmaker()
    fid = uuid.UUID(file_id)
    async with sessionmaker() as session:
        row = await extract_into_row(session, file_id=fid)
        if row is None:
            log.warning("agent.files.ingest_file.row_not_found", file_id=file_id)
            await session.commit()
            return {"file_id": file_id, "status": "not_found"}
        await session.commit()
    log.info(
        "agent.files.ingest_file.done",
        file_id=file_id,
        status=row.status,
        text_chars=(row.metadata_json or {}).get("text_chars", 0),
    )
    return {
        "file_id": file_id,
        "status": row.status,
        "text_chars": (row.metadata_json or {}).get("text_chars", 0),
    }
