"""File schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime_type: str
    kind: str
    size_bytes: int
    sha256: str
    summary: str | None = None
    # Phase 3 async ingestion: pending → processing → ready (or failed).
    # Frontend polls GET /files/{id} until status == "ready".
    status: str = "ready"
    error_message: str | None = None
    created_at: datetime
