"""Files agent — on-demand PDF / DOCX / image ingestion + OCR.

Triggered from `POST /api/v1/files`: the API enqueues an
`ingest_file` task and returns 202 with the run id. The frontend
polls `GET /api/v1/files/{id}` until status flips to `ready` (the
agent updates the row when done). Heavy parses (50-page PDFs,
high-res photos) no longer block the chat orchestrator.

Stub for Phase 3 — concrete implementation lifts the existing
parsing pipeline from `cara.services.files`. Currently this just
records the run so /admin/agents can show it.
"""

from __future__ import annotations

from typing import Any

import structlog

from cara.agents._base import cara_task


log = structlog.get_logger(__name__)


@cara_task(agent="files")
async def ingest_file(
    file_id: str,
    user_id: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Re-parse + index an uploaded file. Idempotency key = `file_id`
    so a re-trigger doesn't re-extract.
    """
    log.info("agent.files.ingest_file.placeholder", file_id=file_id, user_id=user_id)
    # Phase 3: lift parse logic from cara.services.files into here
    # and remove the synchronous path from POST /api/v1/files.
    return {"file_id": file_id, "status": "noop", "phase": "stub"}
